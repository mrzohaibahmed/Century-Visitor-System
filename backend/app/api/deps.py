"""
Shared route dependencies.

Every route MUST declare exactly one access rule:

    dependencies=[Depends(public)]                          # no login needed (health checks, login)
    ctx: AuthContext = Depends(require(Permission.X))       # authenticated + permission

tests/test_route_security.py fails if any route has neither, so a new endpoint
cannot be exposed by accident.

require(permission) establishes identity on the server for every request:
  1. session cookie -> session (hash lookup; idle and absolute expiry) -> user
     (role read from the database, never from the client)
  2. state-changing requests must carry the CSRF token (double submit, bound to
     the session)
  3. accounts that must change their password can only use account endpoints
  4. the role must hold the permission (denials are audited)
"""
from fastapi import Request, Response
from starlette.requests import HTTPConnection

from app.core.config import Settings
from app.core.errors import AppError
from app.core.net import client_ip
from app.core.permissions import Permission, has_permission
from app.core.security import hash_token, tokens_equal
from app.db.client import Database
from app.services import audit
from app.services import auth as auth_service
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, NewSession, RequestMeta

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_COOKIE = "cg_csrf"
CSRF_HEADER = "x-csrf-token"


def public() -> None:
    """Marker: this route is intentionally reachable without logging in."""


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def request_meta(request: HTTPConnection) -> RequestMeta:
    settings: Settings = request.app.state.settings
    return RequestMeta(ip=client_ip(request, settings.trusted_proxies), user_agent=request.headers.get("user-agent"))


def session_cookie_name(settings: Settings) -> str:
    # The __Host- prefix makes browsers insist on Secure, Path=/ and no Domain attribute.
    return "__Host-cg_session" if settings.secure_cookies else "cg_session"


def set_session_cookies(response: Response, settings: Settings, new: NewSession) -> None:
    max_age = settings.session_max_hours * 3600
    response.set_cookie(session_cookie_name(settings), new.token, max_age=max_age, path="/",
                        httponly=True, secure=settings.secure_cookies, samesite="strict")
    # Readable by the page's JavaScript on purpose: it is echoed back in the X-CSRF-Token header.
    response.set_cookie(CSRF_COOKIE, new.csrf_token, max_age=max_age, path="/",
                        httponly=False, secure=settings.secure_cookies, samesite="strict")


def clear_session_cookies(response: Response, settings: Settings) -> None:
    for name, httponly in ((session_cookie_name(settings), True), (CSRF_COOKIE, False)):
        response.delete_cookie(name, path="/", secure=settings.secure_cookies, httponly=httponly, samesite="strict")


def _verify_csrf(request: Request, session: dict) -> None:
    header = request.headers.get(CSRF_HEADER, "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    expected = session.get("csrf_token_hash", "")
    if not (header and cookie and tokens_equal(header, cookie) and tokens_equal(hash_token(header), expected)):
        raise AppError(403, "csrf_failed", "Your session could not be verified. Please reload the page and try again.")


def require(permission: Permission):
    async def dependency(request: Request) -> AuthContext:
        settings: Settings = request.app.state.settings
        db = request.app.state.database.db
        ctx = await auth_service.authenticate(db, settings, request.cookies.get(session_cookie_name(settings)))

        if request.method not in SAFE_METHODS:
            _verify_csrf(request, ctx.session)

        if ctx.user.get("must_change_password") and permission != Permission.ACCOUNT_SELF:
            raise AppError(403, "password_change_required", "You must change your password before continuing.")

        if not has_permission(ctx.user.get("role"), permission):
            await audit.record(db, AuditAction.ACCESS_DENIED, result="DENIED", actor=actor_from_user(ctx.user),
                               ip=request_meta(request).ip,
                               metadata={"permission": str(permission), "method": request.method,
                                         "path": request.url.path})
            raise AppError(403, "forbidden", "You do not have permission to do this.")
        return ctx

    dependency.required_permission = permission   # read by the route-security test
    dependency.__name__ = f"require_{permission.name.lower()}"
    return dependency


def reject_cross_site(request: Request) -> None:
    """Login has no session yet, so CSRF tokens cannot protect it; refuse cross-site
    form posts instead (browsers send Sec-Fetch-Site on every request)."""
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise AppError(403, "cross_site_request", "This request is not allowed.")
