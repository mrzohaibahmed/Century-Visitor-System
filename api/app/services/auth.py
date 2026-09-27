"""
Login, session validation, logout and changing one's own password.

The backend alone decides who the user is: the role and permissions come from
the users collection on every request, never from anything the browser sends.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    burn_verify_time,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    password_policy_error,
    verify_password,
)
from app.db.transactions import run_in_transaction
from app.repositories import rate_limits
from app.repositories import sessions as sessions_repo
from app.repositories import users as users_repo
from app.services import audit
from app.services.audit import AuditAction, actor_from_user

log = logging.getLogger(__name__)

GENERIC_LOGIN_ERROR = "Invalid username or password."
DISABLED_MESSAGE = "This account is disabled. Contact the administrator."
# last_seen_at is written at most this often (the idle timeout is measured in minutes).
LAST_SEEN_WRITE_INTERVAL = timedelta(seconds=60)


@dataclass
class RequestMeta:
    ip: str
    user_agent: str | None = None


@dataclass
class NewSession:
    token: str             # raw value: goes into the HttpOnly cookie only
    csrf_token: str        # raw value: goes into the readable CSRF cookie only
    expires_at: datetime
    user: dict
    session: dict


@dataclass
class AuthContext:
    user: dict
    session: dict


def locked_message(settings: Settings) -> str:
    return (f"Too many failed attempts. This account is locked for {settings.login_lockout_minutes} minutes. "
            "An administrator can unlock it sooner.")


async def login(db: AsyncDatabase, settings: Settings, username: str, password: str, meta: RequestMeta) -> NewSession:
    attempts = await rate_limits.hit(db, f"login-ip:{meta.ip}", settings.login_ip_window_minutes)
    if attempts > settings.login_ip_limit:
        await audit.record(db, AuditAction.LOGIN_FAILED, result="FAILURE", ip=meta.ip,
                           metadata={"reason": "rate_limited"})
        raise AppError(429, "rate_limited",
                       "Too many login attempts from this computer. Please wait a few minutes and try again.")

    user = await users_repo.find_by_username(db, username)
    if user is None:
        await asyncio.to_thread(burn_verify_time, password)
        await audit.record(db, AuditAction.LOGIN_FAILED, result="FAILURE", ip=meta.ip,
                           metadata={"reason": "unknown_user", "username": username[:64]})
        raise AppError(401, "invalid_credentials", GENERIC_LOGIN_ERROR)

    actor = actor_from_user(user)
    now = datetime.now(UTC)
    locked_until = user.get("locked_until")
    if locked_until and locked_until > now:
        # No password check while locked: the lock must stop guessing, not just slow it.
        await audit.record(db, AuditAction.LOGIN_FAILED, result="FAILURE", actor=actor, ip=meta.ip,
                           resource_type="user", resource_id=user["_id"], metadata={"reason": "locked"})
        raise AppError(403, "account_locked", locked_message(settings))

    if not await asyncio.to_thread(verify_password, password, user.get("password_hash", "")):
        just_locked = await users_repo.record_failed_login(
            db, user["_id"], settings.login_max_failures, settings.login_lockout_minutes)
        await audit.record(db, AuditAction.LOGIN_FAILED, result="FAILURE", actor=actor, ip=meta.ip,
                           resource_type="user", resource_id=user["_id"], metadata={"reason": "wrong_password"})
        if just_locked:
            await audit.record(db, AuditAction.ACCOUNT_LOCKED, actor=actor, ip=meta.ip, resource_type="user",
                               resource_id=user["_id"], metadata={"minutes": settings.login_lockout_minutes})
            raise AppError(403, "account_locked", locked_message(settings))
        raise AppError(401, "invalid_credentials", GENERIC_LOGIN_ERROR)

    # Only reported after a correct password, so guessers cannot tell disabled accounts apart.
    if not user.get("is_active", False):
        await audit.record(db, AuditAction.LOGIN_FAILED, result="FAILURE", actor=actor, ip=meta.ip,
                           resource_type="user", resource_id=user["_id"], metadata={"reason": "disabled"})
        raise AppError(403, "account_disabled", DISABLED_MESSAGE)

    new_hash = await asyncio.to_thread(hash_password, password) if needs_rehash(user["password_hash"]) else None
    await users_repo.record_successful_login(db, user["_id"], new_hash)

    token, csrf_token = new_token(), new_token()
    expires_at = now + timedelta(hours=settings.session_max_hours)
    session = {
        "token_hash": hash_token(token),
        "csrf_token_hash": hash_token(csrf_token),
        "user_id": user["_id"],
        "gate_id": None,                 # gate selection arrives with gates (Phase 3)
        "created_at": now,
        "last_seen_at": now,
        "expires_at": expires_at,
        "revoked_at": None,
        "ip": meta.ip,
        "user_agent": (meta.user_agent or "")[:256],
    }
    session["_id"] = await sessions_repo.insert(db, session)
    await audit.record(db, AuditAction.LOGIN, actor=actor, ip=meta.ip, resource_type="session",
                       resource_id=session["_id"], metadata={"rehashed": bool(new_hash)})
    return NewSession(token, csrf_token, expires_at, user, session)


async def authenticate(db: AsyncDatabase, settings: Settings, token: str | None) -> AuthContext:
    if not token:
        raise AppError(401, "unauthenticated", "Please log in.")
    session = await sessions_repo.find_active_by_token_hash(db, hash_token(token))
    if session is None:
        raise AppError(401, "unauthenticated", "Please log in.")

    now = datetime.now(UTC)
    idle_deadline = session["last_seen_at"] + timedelta(minutes=settings.session_idle_minutes)
    if session["expires_at"] <= now or idle_deadline <= now:
        await sessions_repo.revoke(db, session["_id"], "expired")
        raise AppError(401, "session_expired", "Your session has expired. Please log in again.")

    user = await users_repo.find_by_id(db, session["user_id"])
    if user is None or not user.get("is_active", False):
        await sessions_repo.revoke(db, session["_id"], "user_inactive")
        raise AppError(401, "unauthenticated", "Please log in.")

    if now - session["last_seen_at"] >= LAST_SEEN_WRITE_INTERVAL:
        await sessions_repo.touch(db, session["_id"], now)
        session["last_seen_at"] = now
    return AuthContext(user, session)


async def logout(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta) -> None:
    await sessions_repo.revoke(db, ctx.session["_id"], "logout")
    await audit.record(db, AuditAction.LOGOUT, actor=actor_from_user(ctx.user), ip=meta.ip,
                       resource_type="session", resource_id=ctx.session["_id"])


async def verify_actor_password(db: AsyncDatabase, settings: Settings, ctx: AuthContext, password: str | None,
                                meta: RequestMeta) -> None:
    """Re-authentication for sensitive actions. Wrong passwords count towards the lockout."""
    if not password:
        raise AppError(403, "reauthentication_required", "Enter your password to confirm this change.")
    if not await asyncio.to_thread(verify_password, password, ctx.user.get("password_hash", "")):
        await users_repo.record_failed_login(db, ctx.user["_id"], settings.login_max_failures,
                                             settings.login_lockout_minutes)
        await audit.record(db, AuditAction.LOGIN_FAILED, result="FAILURE", actor=actor_from_user(ctx.user),
                           ip=meta.ip, resource_type="user", resource_id=ctx.user["_id"],
                           metadata={"reason": "reauthentication_failed"})
        raise AppError(403, "reauthentication_failed", "Your password is incorrect. The change was not made.")


async def change_own_password(db: AsyncDatabase, settings: Settings, ctx: AuthContext, current_password: str,
                              new_password: str, meta: RequestMeta) -> None:
    user = ctx.user
    if not await asyncio.to_thread(verify_password, current_password, user.get("password_hash", "")):
        await users_repo.record_failed_login(db, user["_id"], settings.login_max_failures,
                                             settings.login_lockout_minutes)
        await audit.record(db, AuditAction.PASSWORD_CHANGED, result="FAILURE", actor=actor_from_user(user),
                           ip=meta.ip, resource_type="user", resource_id=user["_id"],
                           metadata={"reason": "current_password_incorrect"})
        raise AppError(400, "current_password_incorrect", "The current password is incorrect.")
    if new_password == current_password:
        raise AppError(422, "password_unchanged", "The new password must be different from the current one.")
    problem = password_policy_error(new_password, user["username"])
    if problem:
        raise AppError(422, "weak_password", problem)

    new_hash = await asyncio.to_thread(hash_password, new_password)

    async def work(s: AsyncClientSession):
        await users_repo.update_fields(db, user["_id"], {
            "password_hash": new_hash, "must_change_password": False,
            "password_changed_at": datetime.now(UTC), "failed_login_count": 0, "locked_until": None}, session=s)
        # Other devices signed in with the old password are signed out.
        await sessions_repo.revoke_all_for_user(db, user["_id"], "password_changed",
                                                except_session_id=ctx.session["_id"], session=s)
        await audit.record(db, AuditAction.PASSWORD_CHANGED, actor=actor_from_user(user), ip=meta.ip,
                           resource_type="user", resource_id=user["_id"], session=s)

    await run_in_transaction(db, work)
