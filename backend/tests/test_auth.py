"""Login, sessions, CSRF, lockout, rate limiting and changing one's own password."""
import logging
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher

from app.core import security
from app.core.security import hash_token
from app.services import auth as auth_service
from tests.conftest import ADMIN_PASSWORD, GUARD_PASSWORD, make_settings

pytestmark = pytest.mark.anyio

LOGIN = "/api/v1/auth/login"
ME = "/api/v1/auth/me"
LOGOUT = "/api/v1/auth/logout"
CHANGE = "/api/v1/auth/change-password"


def cookie_header(response, name):
    return next(h for h in response.headers.get_list("set-cookie") if h.startswith(f"{name}="))


# ---------------------------------------------------------------- login & session
async def test_login_sets_secure_cookies_and_returns_the_user(harness):
    await harness.create_user("guard1", GUARD_PASSWORD, "GUARD")
    r = await harness.client().login("guard1", GUARD_PASSWORD)
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["username"] == "guard1" and body["user"]["role"] == "GUARD"
    assert "visit:check_in" in body["permissions"] and "users:manage" not in body["permissions"]
    session_cookie = cookie_header(r, "__Host-cg_session").lower()
    for flag in ("httponly", "secure", "samesite=strict", "path=/"):
        assert flag in session_cookie
    assert "domain=" not in session_cookie
    csrf_cookie = cookie_header(r, "cg_csrf").lower()
    assert "httponly" not in csrf_cookie and "secure" in csrf_cookie and "samesite=strict" in csrf_cookie


async def test_only_token_hashes_are_stored(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    c = harness.client()
    await c.login("guard1", GUARD_PASSWORD)
    token = c.cookies.get("__Host-cg_session")
    session = await harness.db.sessions.find_one({})
    assert session["token_hash"] == hash_token(token)
    assert token not in str(session) and c.cookies.get("cg_csrf") not in str(session)


async def test_responses_never_contain_secrets(guard):
    body = (await guard.get(ME)).text
    for secret in ("password_hash", "token_hash", "csrf_token_hash", GUARD_PASSWORD):
        assert secret not in body


async def test_me_requires_a_session(harness):
    r = await harness.client().get(ME)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthenticated"


async def test_forged_session_cookie_is_rejected(harness):
    c = harness.client()
    c.cookies.set("__Host-cg_session", "forged-token-value")
    assert (await c.get(ME)).status_code == 401


async def test_username_is_matched_case_insensitively(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    assert (await harness.client().login("GUARD1", GUARD_PASSWORD)).status_code == 200


async def test_login_body_rejects_unknown_fields(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    r = await harness.client().post(LOGIN, json={"username": "guard1", "password": GUARD_PASSWORD, "role": "ADMIN"})
    assert r.status_code == 422


async def test_cross_site_login_is_refused(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    r = await harness.client().post(LOGIN, json={"username": "guard1", "password": GUARD_PASSWORD},
                                    headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


# ---------------------------------------------------------------- failures, lockout, enumeration
async def test_wrong_password_and_unknown_user_look_the_same(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    wrong = await harness.client().login("guard1", "Wrong-Password-1")
    unknown = await harness.client().login("nobody", "Wrong-Password-1")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"] == "Invalid username or password."
    assert wrong.json()["error"]["code"] == unknown.json()["error"]["code"]


async def test_unknown_user_costs_the_same_hashing_work(harness, monkeypatch):
    calls = []
    monkeypatch.setattr(auth_service, "burn_verify_time", lambda pw: calls.append(pw))
    await harness.client().login("nobody", "Some-Password-1")
    assert calls == ["Some-Password-1"]


async def test_account_locks_after_repeated_failures(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    c = harness.client()
    for _ in range(4):
        assert (await c.login("guard1", "Wrong-Password-1")).status_code == 401
    locked = await c.login("guard1", "Wrong-Password-1")
    assert locked.status_code == 403 and locked.json()["error"]["code"] == "account_locked"
    # even the right password is refused while locked
    assert (await c.login("guard1", GUARD_PASSWORD)).json()["error"]["code"] == "account_locked"
    assert await harness.db.audit_logs.count_documents({"action": "ACCOUNT_LOCKED"}) == 1


async def test_lock_expires_and_success_resets_the_counter(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    c = harness.client()
    for _ in range(5):
        await c.login("guard1", "Wrong-Password-1")
    await harness.db.users.update_one({"username": "guard1"},
                                      {"$set": {"locked_until": datetime.now(UTC) - timedelta(seconds=1)}})
    assert (await c.login("guard1", GUARD_PASSWORD)).status_code == 200
    user = await harness.db.users.find_one({"username": "guard1"})
    assert user["failed_login_count"] == 0 and user["locked_until"] is None


async def test_disabled_account_is_only_revealed_to_the_right_password(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    await harness.db.users.update_one({"username": "guard1"}, {"$set": {"is_active": False}})
    wrong = await harness.client().login("guard1", "Wrong-Password-1")
    right = await harness.client().login("guard1", GUARD_PASSWORD)
    assert wrong.json()["error"]["code"] == "invalid_credentials"
    assert right.status_code == 403 and right.json()["error"]["code"] == "account_disabled"


async def test_failed_logins_are_audited_without_passwords(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    await harness.client().login("guard1", "Wrong-Secret-9")
    await harness.client().login("ghost", "Other-Secret-9")
    failed = await harness.db.audit_logs.find({"action": "LOGIN_FAILED"}).to_list(None)
    reasons = sorted(d["metadata"]["reason"] for d in failed)
    assert reasons == ["unknown_user", "wrong_password"]
    everything = str(await harness.db.audit_logs.find({}).to_list(None))
    assert "Wrong-Secret-9" not in everything and "Other-Secret-9" not in everything


async def test_passwords_are_never_logged(harness, caplog):
    caplog.set_level(logging.DEBUG)
    await harness.create_user("guard1", GUARD_PASSWORD)
    await harness.client().login("guard1", GUARD_PASSWORD)
    await harness.client().login("guard1", "Wrong-Secret-9")
    assert GUARD_PASSWORD not in caplog.text and "Wrong-Secret-9" not in caplog.text


# ---------------------------------------------------------------- rate limiting
async def test_login_rate_limit_per_client_ip(settings, client_for):
    from app.core.permissions import Role
    from app.db.migrate import apply_schema
    from app.main import create_app
    from app.services.users import create_user
    s = make_settings(mongo_db=settings.mongo_db, login_ip_limit=3)
    app = create_app(s)
    async for client in client_for(app):
        await apply_schema(app.state.database.db)
        await create_user(app.state.database.db, actor=None, meta=None, username="guard1", display_name="G",
                          role=Role.GUARD, password=GUARD_PASSWORD, must_change_password=False)
        gate1 = {"X-Forwarded-For": "10.0.0.11"}
        for _ in range(3):
            await client.post(LOGIN, json={"username": "guard1", "password": "Wrong-Password-1"}, headers=gate1)
        blocked = await client.post(LOGIN, json={"username": "guard1", "password": GUARD_PASSWORD}, headers=gate1)
        other_gate = await client.post(LOGIN, json={"username": "guard1", "password": GUARD_PASSWORD},
                                       headers={"X-Forwarded-For": "10.0.0.12"})
    assert blocked.status_code == 429 and blocked.json()["error"]["code"] == "rate_limited"
    assert other_gate.status_code == 200


def test_forwarded_for_is_only_trusted_from_trusted_proxies():
    from starlette.requests import Request

    from app.core.net import client_ip

    def req(peer, xff=None):
        headers = [(b"x-forwarded-for", xff.encode())] if xff else []
        return Request({"type": "http", "client": (peer, 1234), "headers": headers})

    assert client_ip(req("127.0.0.1", "10.0.0.5"), ["127.0.0.1"]) == "10.0.0.5"
    assert client_ip(req("10.9.9.9", "1.2.3.4"), ["127.0.0.1"]) == "10.9.9.9"       # spoofing attempt ignored
    assert client_ip(req("127.0.0.1", "6.6.6.6, 10.0.0.5"), ["127.0.0.1"]) == "10.0.0.5"  # rightmost untrusted hop
    assert client_ip(req("127.0.0.1", "garbage"), ["127.0.0.1"]) == "127.0.0.1"


# ---------------------------------------------------------------- expiry
async def test_idle_session_expires(harness, guard):
    await harness.db.sessions.update_many({}, {"$set": {"last_seen_at": datetime.now(UTC) - timedelta(minutes=16)}})
    r = await guard.get(ME)
    assert r.status_code == 401 and r.json()["error"]["code"] == "session_expired"
    assert (await harness.db.sessions.find_one({}))["revoked_at"] is not None


async def test_absolute_session_expiry(harness, guard):
    await harness.db.sessions.update_many({}, {"$set": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)}})
    assert (await guard.get(ME)).json()["error"]["code"] == "session_expired"


async def test_activity_is_recorded_at_most_once_a_minute(harness, guard):
    before = (await harness.db.sessions.find_one({}))["last_seen_at"]
    await guard.get(ME)
    assert (await harness.db.sessions.find_one({}))["last_seen_at"] == before
    await harness.db.sessions.update_many({}, {"$set": {"last_seen_at": datetime.now(UTC) - timedelta(minutes=2)}})
    await guard.get(ME)
    assert (await harness.db.sessions.find_one({}))["last_seen_at"] > datetime.now(UTC) - timedelta(seconds=30)


async def test_disabling_a_user_ends_their_session_immediately(harness, guard):
    await harness.db.users.update_one({"username": "guard1"}, {"$set": {"is_active": False}})
    assert (await guard.get(ME)).status_code == 401


# ---------------------------------------------------------------- CSRF & logout
async def test_state_changes_require_the_csrf_token(guard):
    body = {"current_password": GUARD_PASSWORD, "new_password": "New-Guard-Pass-2"}
    missing = await guard.post_without_csrf(CHANGE, json=body)
    wrong = await guard.post_without_csrf(CHANGE, json=body, headers={"X-CSRF-Token": "not-the-token"})
    assert missing.status_code == wrong.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_failed"


async def test_csrf_token_is_bound_to_its_session(harness, guard):
    await harness.create_user("guard2", "Guard-Two-Pass-1")
    other = await harness.logged_in("guard2", "Guard-Two-Pass-1")
    stolen = other.cookies.get("cg_csrf")
    guard.cookies.set("cg_csrf", stolen)
    r = await guard.post_without_csrf(LOGOUT, headers={"X-CSRF-Token": stolen})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"


async def test_logout_revokes_the_session_and_clears_cookies(harness, guard):
    r = await guard.post(LOGOUT)
    assert r.status_code == 204
    cleared = " ".join(r.headers.get_list("set-cookie")).lower()
    assert "__host-cg_session=" in cleared and "max-age=0" in cleared
    assert (await harness.db.sessions.find_one({}))["revoked_reason"] == "logout"
    assert await harness.db.audit_logs.count_documents({"action": "LOGOUT"}) == 1


# ---------------------------------------------------------------- change own password
async def test_change_password(harness, guard):
    second_device = await harness.logged_in("guard1", GUARD_PASSWORD)
    r = await guard.post(CHANGE, json={"current_password": GUARD_PASSWORD, "new_password": "New-Guard-Pass-2"})
    assert r.status_code == 204
    assert (await guard.get(ME)).status_code == 200              # this session stays
    assert (await second_device.get(ME)).status_code == 401      # other sessions are signed out
    assert (await harness.client().login("guard1", GUARD_PASSWORD)).status_code == 401
    assert (await harness.client().login("guard1", "New-Guard-Pass-2")).status_code == 200
    assert await harness.db.audit_logs.count_documents({"action": "PASSWORD_CHANGED", "result": "SUCCESS"}) == 1


@pytest.mark.parametrize("current,new,status,code", [
    ("Wrong-Current-1", "New-Guard-Pass-2", 400, "current_password_incorrect"),
    (GUARD_PASSWORD, GUARD_PASSWORD, 422, "password_unchanged"),
    (GUARD_PASSWORD, "short", 422, "weak_password"),
    (GUARD_PASSWORD, "guard1-is-my-password", 422, "weak_password"),
])
async def test_invalid_password_changes(guard, current, new, status, code):
    r = await guard.post(CHANGE, json={"current_password": current, "new_password": new})
    assert r.status_code == status and r.json()["error"]["code"] == code


async def test_new_accounts_must_change_their_password_first(harness):
    await harness.create_user("newadmin", ADMIN_PASSWORD, "ADMIN", must_change_password=True)
    c = await harness.logged_in("newadmin", ADMIN_PASSWORD)
    assert (await c.get(ME)).json()["user"]["must_change_password"] is True
    blocked = await c.get("/api/v1/users")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "password_change_required"
    await c.post(CHANGE, json={"current_password": ADMIN_PASSWORD, "new_password": "Fresh-Admin-Pass-2"})
    assert (await c.get("/api/v1/users")).status_code == 200


# ---------------------------------------------------------------- hashing
def test_production_password_hashing_parameters():
    ph = PasswordHasher()
    assert ph.type.name == "ID"                                 # argon2id
    assert ph.memory_cost >= 19 * 1024 and ph.time_cost >= 2    # at or above the OWASP minimum
    assert ph.hash("x-y-z-w-v").startswith("$argon2id$")


async def test_weaker_hashes_are_upgraded_at_login(harness):
    await harness.create_user("guard1", GUARD_PASSWORD)
    old_hash = (await harness.db.users.find_one({"username": "guard1"}))["password_hash"]
    security.use_hasher(PasswordHasher(time_cost=2, memory_cost=16, parallelism=1))
    assert (await harness.client().login("guard1", GUARD_PASSWORD)).status_code == 200
    new_hash = (await harness.db.users.find_one({"username": "guard1"}))["password_hash"]
    assert new_hash != old_hash and "m=16,t=2" in new_hash
