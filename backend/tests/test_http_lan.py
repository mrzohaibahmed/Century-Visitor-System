"""Production deployment mode http-lan: plain HTTP on a trusted LAN (CG_DEPLOYMENT_MODE=http-lan).

Only the Secure flag (and with it the __Host- prefix) is dropped from the session and CSRF cookies, and
only for production explicitly configured that way. Normal production, development and test keep their
cookies exactly as before.
"""
import shutil
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import Response
from pydantic import ValidationError
from pymongo import MongoClient

from app import serve
from app.api.deps import clear_session_cookies, session_cookie_name, set_session_cookies
from app.core.config import Settings
from app.db.migrate import apply_schema
from app.main import create_app
from app.services.auth import NewSession
from tests.conftest import (
    ADMIN_PASSWORD,
    GUARD_PASSWORD,
    PRODUCTION_LIKE_URI,
    TEST_MONGO_URI,
    ApiClient,
    AuthHarness,
    make_settings,
)

ME = "/api/v1/auth/me"
LOGOUT = "/api/v1/auth/logout"
CHANGE = "/api/v1/auth/change-password"


def http_lan(**overrides) -> Settings:
    return make_settings(environment="production", deployment_mode="http-lan", **overrides)


def cookie_headers(response) -> dict[str, str]:
    """name -> the whole Set-Cookie header, lower-cased (httpx or Starlette response)."""
    headers = response.headers
    values = headers.get_list("set-cookie") if hasattr(headers, "get_list") else headers.getlist("set-cookie")
    return {h.split("=", 1)[0]: h.lower() for h in values}


def attributes(header: str) -> set[str]:
    return {part.strip().split("=", 1)[0] for part in header.split(";")[1:]}


def issued_cookies(settings: Settings) -> dict[str, str]:
    response = Response()
    set_session_cookies(response, settings, NewSession("session-token", "csrf-token", datetime.now(UTC), {}, {}))
    return cookie_headers(response)


# ---------------------------------------------------------------- configuration
def test_production_defaults_to_https_with_secure_cookies():
    s = make_settings(environment="production")
    assert s.deployment_mode == "https" and s.secure_cookies is True
    assert session_cookie_name(s) == "__Host-cg_session"


def test_production_http_lan_drops_secure():
    s = http_lan()
    assert s.environment == "production" and s.deployment_mode == "http-lan"
    assert s.secure_cookies is False and session_cookie_name(s) == "cg_session"


@pytest.mark.parametrize("environment", ["production", "development", "test"])
@pytest.mark.parametrize("mode", ["http", "HTTP-LAN", "http_lan", "lan", "insecure", ""])
def test_an_unknown_deployment_mode_is_refused(environment, mode):
    with pytest.raises(ValidationError, match="deployment_mode"):
        make_settings(environment=environment, deployment_mode=mode)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_http_lan_is_refused_outside_production(environment):
    with pytest.raises(ValidationError, match="production deployment mode"):
        make_settings(environment=environment, deployment_mode="http-lan")


@pytest.mark.parametrize("mode", ["https", "http-lan"])
def test_production_still_refuses_cookie_secure_false(mode):
    """CG_DEPLOYMENT_MODE is the only way to drop Secure in production; CG_COOKIE_SECURE=false never is."""
    with pytest.raises(ValidationError, match="cookie_secure must be true in production"):
        make_settings(environment="production", deployment_mode=mode, cookie_secure=False)


@pytest.mark.parametrize("environment", ["development", "test"])
def test_development_and_test_cookies_are_unchanged(environment):
    assert make_settings(environment=environment).secure_cookies is True
    assert session_cookie_name(make_settings(environment=environment)) == "__Host-cg_session"
    # A plain-HTTP development or test network may still switch Secure off, as before.
    s = make_settings(environment=environment, cookie_secure=False)
    assert s.deployment_mode == "https" and s.secure_cookies is False and session_cookie_name(s) == "cg_session"


def test_the_mode_is_read_from_the_environment(monkeypatch, tmp_path):
    for key, value in {"CG_ENVIRONMENT": "production", "CG_MONGO_URI": PRODUCTION_LIKE_URI,
                       "CG_PHOTO_DIR": str(tmp_path), "CG_DEPLOYMENT_MODE": "http-lan"}.items():
        monkeypatch.setenv(key, value)
    assert Settings(_env_file=None).secure_cookies is False


# ---------------------------------------------------------------- the production server (python -m app.serve)
@pytest.fixture
def production_env(monkeypatch, tmp_path):
    for key, value in {"CG_ENVIRONMENT": "production", "CG_MONGO_URI": PRODUCTION_LIKE_URI,
                       "CG_PHOTO_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(key, value)
    calls = []
    monkeypatch.setattr(serve.uvicorn, "run", lambda **kw: calls.append(kw))
    return calls


def test_the_production_server_starts_in_http_lan_mode(production_env, monkeypatch):
    monkeypatch.setenv("CG_DEPLOYMENT_MODE", "http-lan")
    assert serve.main([]) == 0
    # Only the cookies change: still loopback, no reload, no proxy headers.
    options = production_env[0]
    assert options["host"] == "127.0.0.1" and options["reload"] is False and options["proxy_headers"] is False


def test_the_production_server_refuses_an_unknown_mode(production_env, monkeypatch, capsys):
    monkeypatch.setenv("CG_DEPLOYMENT_MODE", "http")
    assert serve.main([]) == 2 and "CG_DEPLOYMENT_MODE" in capsys.readouterr().err and not production_env


# ---------------------------------------------------------------- cookie attributes
def test_production_https_cookie_attributes():
    cookies = issued_cookies(make_settings(environment="production"))
    assert set(cookies) == {"__Host-cg_session", "cg_csrf"}
    session, csrf = cookies["__Host-cg_session"], cookies["cg_csrf"]
    assert attributes(session) == {"httponly", "max-age", "path", "samesite", "secure"}
    assert "samesite=strict" in session and "path=/" in session and "max-age=43200" in session
    assert attributes(csrf) == {"max-age", "path", "samesite", "secure"}           # readable by the page
    assert "samesite=strict" in csrf and "path=/" in csrf


def test_production_http_lan_cookie_attributes():
    cookies = issued_cookies(http_lan())
    assert set(cookies) == {"cg_session", "cg_csrf"}
    session, csrf = cookies["cg_session"], cookies["cg_csrf"]
    assert attributes(session) == {"httponly", "max-age", "path", "samesite"}      # no secure, no domain
    assert "samesite=strict" in session and "path=/" in session and "max-age=43200" in session
    assert attributes(csrf) == {"max-age", "path", "samesite"}                     # not httponly: readable
    assert "samesite=strict" in csrf and "path=/" in csrf


def test_http_lan_never_issues_a_host_prefixed_cookie_without_secure():
    """__Host- requires Secure (browsers drop it otherwise): the two must never part."""
    for s in (http_lan(), make_settings(environment="production"), make_settings(cookie_secure=False),
              make_settings()):
        for name, header in issued_cookies(s).items():
            assert not name.startswith("__Host-") or "secure" in attributes(header)
    assert "__Host-cg_session" not in issued_cookies(http_lan())


def test_http_lan_logout_clears_the_cookies_it_issued():
    response = Response()
    clear_session_cookies(response, http_lan())
    cleared = cookie_headers(response)
    assert set(cleared) == {"cg_session", "cg_csrf"}
    for header in cleared.values():
        assert "max-age=0" in header and "path=/" in header and "secure" not in attributes(header)


# ---------------------------------------------------------------- the whole flow over plain HTTP
class HttpHarness(AuthHarness):
    """Clients on http:// (like a gate PC browser on the LAN): they keep and send cookies only when
    those cookies are not Secure, as a browser would."""

    def __init__(self, app, db, base_url: str):
        super().__init__(app, db)
        self.base_url = base_url

    def client(self) -> ApiClient:
        c = ApiClient(transport=httpx.ASGITransport(app=self.app, raise_app_exceptions=False), base_url=self.base_url)
        self._clients.append(c)
        return c


async def _harness(settings: Settings, base_url: str):
    settings.photo_dir.mkdir(parents=True, exist_ok=True)       # production never creates it
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            await apply_schema(app.state.database.db)
            h = HttpHarness(app, app.state.database.db, base_url)
            yield h
            await h.close()
    finally:
        MongoClient(TEST_MONGO_URI).drop_database(settings.mongo_db)
        shutil.rmtree(settings.photo_dir, ignore_errors=True)


def _production(**overrides) -> Settings:
    # A real (loopback, no-login) test database, accepted in production only with this explicit setting.
    return make_settings(environment="production", mongo_uri=TEST_MONGO_URI, mongo_localhost_without_login=True,
                         email_worker=False, **overrides)


@pytest.fixture
async def lan():
    async for h in _harness(_production(deployment_mode="http-lan"), "http://vms-server:3000"):
        yield h


@pytest.fixture
async def https_production():
    async for h in _harness(_production(), "https://vms-server"):
        yield h


@pytest.mark.anyio
async def test_http_lan_login_gives_a_working_session_over_http(lan):
    await lan.create_user("guard1", GUARD_PASSWORD, "GUARD")
    c = lan.client()
    r = await c.login("guard1", GUARD_PASSWORD)
    assert r.status_code == 200
    assert set(cookie_headers(r)) == {"cg_session", "cg_csrf"}
    assert c.cookies.get("cg_session") and c.cookies.get("cg_csrf")              # kept over http://
    me = await c.get(ME)
    assert me.status_code == 200 and me.json()["user"]["username"] == "guard1"


@pytest.mark.anyio
async def test_http_lan_still_requires_the_csrf_token(lan):
    await lan.create_user("guard1", GUARD_PASSWORD, "GUARD")
    c = await lan.logged_in("guard1", GUARD_PASSWORD)
    r = await c.post_without_csrf(LOGOUT)
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    assert (await c.get(ME)).status_code == 200


@pytest.mark.anyio
async def test_http_lan_logout_revokes_the_session_and_clears_its_cookies(lan):
    await lan.create_user("guard1", GUARD_PASSWORD, "GUARD")
    c = await lan.logged_in("guard1", GUARD_PASSWORD)
    token = c.cookies.get("cg_session")
    r = await c.post(LOGOUT)
    assert r.status_code == 204
    cleared = cookie_headers(r)
    assert set(cleared) == {"cg_session", "cg_csrf"} and all("max-age=0" in h for h in cleared.values())
    assert (await lan.db.sessions.find_one({}))["revoked_reason"] == "logout"
    replay = lan.client()
    replay.cookies.set("cg_session", token)
    assert (await replay.get(ME)).status_code == 401                              # revoked on the server


@pytest.mark.anyio
async def test_http_lan_password_change_and_admin_reset_revoke_sessions(lan):
    await lan.create_user("guard1", GUARD_PASSWORD, "GUARD")
    await lan.create_user("admin", ADMIN_PASSWORD, "ADMIN")
    first = await lan.logged_in("guard1", GUARD_PASSWORD)
    second = await lan.logged_in("guard1", GUARD_PASSWORD)
    r = await first.post(CHANGE, json={"current_password": GUARD_PASSWORD, "new_password": "New-Guard-Pass-2"})
    assert r.status_code == 204
    assert (await second.get(ME)).status_code == 401 and (await first.get(ME)).status_code == 200

    admin = await lan.logged_in("admin", ADMIN_PASSWORD)
    guard = await lan.db.users.find_one({"username": "guard1"})
    r = await admin.post(f"/api/v1/users/{guard['_id']}/reset-password",
                         json={"new_password": "Reset-Guard-Pass-3", "confirm_password": ADMIN_PASSWORD})
    assert r.status_code == 204, r.text
    assert (await first.get(ME)).status_code == 401


@pytest.mark.anyio
async def test_https_production_cookies_are_not_kept_over_plain_http(https_production):
    """Normal production is unchanged: Secure, __Host- cookies, which a browser on http:// cannot keep."""
    await https_production.create_user("guard1", GUARD_PASSWORD, "GUARD")
    c = https_production.client()
    r = await c.login("guard1", GUARD_PASSWORD)
    assert r.status_code == 200 and set(cookie_headers(r)) == {"__Host-cg_session", "cg_csrf"}
    assert (await c.get(ME)).status_code == 200                                   # over https://
    plain = https_production.client()
    plain.cookies = c.cookies
    assert (await plain.get("http://vms-server" + ME)).status_code == 401         # Secure: not sent on http://


@pytest.mark.anyio
async def test_http_lan_answers_over_http_without_hsts_or_a_redirect(lan):
    """HSTS and the HTTP -> HTTPS redirect belonged to Caddy only: the application itself sends neither."""
    await lan.create_user("guard1", GUARD_PASSWORD, "GUARD")
    c = lan.client()
    responses = [await c.login("guard1", GUARD_PASSWORD), await c.get(ME),
                 await c.get("/api/v1/health/ready"), await c.post(LOGOUT)]
    for r in responses:
        assert r.status_code < 300 and "location" not in r.headers
        assert "strict-transport-security" not in r.headers
