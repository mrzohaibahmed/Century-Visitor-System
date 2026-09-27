"""User administration: RBAC, validation, re-authentication, last-admin protection, audit."""
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import audit as audit_module
from tests.conftest import ADMIN_PASSWORD, GUARD_PASSWORD, TEST_MONGO_URI

pytestmark = pytest.mark.anyio

USERS = "/api/v1/users"
ME = "/api/v1/auth/me"
NEW_USER = {"username": "guard2", "display_name": "Gate Two", "role": "GUARD", "password": "Temp-Guard-Pass-1"}


async def user_id(harness, username):
    return str((await harness.db.users.find_one({"username": username}))["_id"])


# ---------------------------------------------------------------- RBAC
@pytest.mark.parametrize("method,path", [
    ("GET", USERS), ("POST", USERS), ("GET", f"{USERS}/000000000000000000000000"),
    ("PATCH", f"{USERS}/000000000000000000000000"), ("POST", f"{USERS}/000000000000000000000000/unlock"),
    ("POST", f"{USERS}/000000000000000000000000/reset-password"),
])
async def test_guards_cannot_use_user_administration(harness, guard, method, path):
    r = await guard.request(method, path, json={"display_name": "x", "new_password": "x"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"


async def test_denied_access_is_audited(harness, guard):
    await guard.get(USERS)
    entry = await harness.db.audit_logs.find_one({"action": "ACCESS_DENIED"})
    assert entry["result"] == "DENIED" and entry["actor"]["username"] == "guard1"
    assert entry["metadata"]["permission"] == "users:manage"


async def test_anonymous_requests_are_rejected(harness):
    assert (await harness.client().get(USERS)).status_code == 401


# ---------------------------------------------------------------- listing & creating
async def test_admin_lists_users_without_secrets(harness, admin, guard):
    r = await admin.get(USERS)
    assert r.status_code == 200
    assert sorted(u["username"] for u in r.json()["items"]) == ["admin", "guard1"]
    assert "password_hash" not in r.text


async def test_admin_creates_a_user_who_must_change_the_password(harness, admin):
    r = await admin.post(USERS, json=NEW_USER)
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "guard2" and body["role"] == "GUARD" and body["must_change_password"] is True
    entry = await harness.db.audit_logs.find_one({"action": "USER_CREATED"})
    assert entry["actor"]["username"] == "admin" and entry["changes"]["role"] == "GUARD"
    assert "Temp-Guard-Pass-1" not in str(entry)


@pytest.mark.parametrize("username", ["guard2", "GUARD2", "Guard2"])
async def test_existing_usernames_are_never_overwritten(harness, admin, username):
    await admin.post(USERS, json=NEW_USER)
    r = await admin.post(USERS, json={**NEW_USER, "username": username, "role": "ADMIN"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "username_taken"
    assert (await harness.db.users.find_one({"username": "guard2"}))["role"] == "GUARD"


@pytest.mark.parametrize("change,status", [
    ({"username": "ab"}, 422), ({"username": "has space"}, 422), ({"username": "-dash"}, 422),
    ({"role": "SUPERUSER"}, 422), ({"display_name": ""}, 422),
    ({"password": "short"}, 422), ({"password": "guard2-password"}, 422),
    ({"is_active": False}, 422), ({"password_hash": "x"}, 422),          # mass assignment
])
async def test_invalid_new_users_are_refused(harness, admin, change, status):
    r = await admin.post(USERS, json={**NEW_USER, **change})
    assert r.status_code == status
    assert await harness.db.users.find_one({"username": NEW_USER["username"]}) is None


@pytest.mark.parametrize("bad_id", ["not-an-id", "000000000000000000000000"])
async def test_unknown_user_ids_are_404(admin, bad_id):
    assert (await admin.get(f"{USERS}/{bad_id}")).status_code == 404


# ---------------------------------------------------------------- updating
async def test_display_name_change_needs_no_reauthentication(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    r = await admin.patch(f"{USERS}/{uid}", json={"display_name": "Main Gate Guard"})
    assert r.status_code == 200 and r.json()["display_name"] == "Main Gate Guard"
    entry = await harness.db.audit_logs.find_one({"action": "USER_UPDATED"})
    assert entry["changes"]["display_name"]["to"] == "Main Gate Guard"


@pytest.mark.parametrize("confirm,code", [(None, "reauthentication_required"),
                                          ("Wrong-Password-1", "reauthentication_failed")])
async def test_role_change_requires_the_admins_password(harness, admin, guard, confirm, code):
    uid = await user_id(harness, "guard1")
    body = {"role": "ADMIN"} | ({"confirm_password": confirm} if confirm else {})
    r = await admin.patch(f"{USERS}/{uid}", json=body)
    assert r.status_code == 403 and r.json()["error"]["code"] == code
    assert (await harness.db.users.find_one({"username": "guard1"}))["role"] == "GUARD"


async def test_role_change_applies_to_the_next_request(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    assert (await guard.get(USERS)).status_code == 403
    r = await admin.patch(f"{USERS}/{uid}", json={"role": "ADMIN", "confirm_password": ADMIN_PASSWORD})
    assert r.status_code == 200
    assert (await guard.get(USERS)).status_code == 200            # the role is read from the database each time
    entry = await harness.db.audit_logs.find_one({"action": "ROLE_CHANGED"})
    assert entry["changes"]["role"] == {"from": "GUARD", "to": "ADMIN"}


async def test_disabling_signs_the_user_out_and_blocks_login(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    r = await admin.patch(f"{USERS}/{uid}", json={"is_active": False, "confirm_password": ADMIN_PASSWORD})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (await guard.get(ME)).status_code == 401
    assert (await harness.client().login("guard1", GUARD_PASSWORD)).json()["error"]["code"] == "account_disabled"
    await admin.patch(f"{USERS}/{uid}", json={"is_active": True, "confirm_password": ADMIN_PASSWORD})
    assert (await harness.client().login("guard1", GUARD_PASSWORD)).status_code == 200
    actions = [d["action"] async for d in harness.db.audit_logs.find({"action": {"$in": ["USER_DISABLED",
                                                                                            "USER_ENABLED"]}})]
    assert actions == ["USER_DISABLED", "USER_ENABLED"]


@pytest.mark.parametrize("change", [{"role": "GUARD"}, {"is_active": False}])
async def test_admins_cannot_demote_or_disable_themselves(harness, admin, change):
    uid = await user_id(harness, "admin")
    r = await admin.patch(f"{USERS}/{uid}", json={**change, "confirm_password": ADMIN_PASSWORD})
    assert r.status_code == 400 and r.json()["error"]["code"] == "cannot_modify_self"


async def test_empty_update_is_rejected(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    assert (await admin.patch(f"{USERS}/{uid}", json={})).status_code == 422


async def test_two_admins_disabling_each_other_at_once_leave_one_admin(harness, admin):
    await harness.create_user("admin2", "Admin-Two-Pass-1", "ADMIN")
    admin2 = await harness.logged_in("admin2", "Admin-Two-Pass-1")
    id1, id2 = await user_id(harness, "admin"), await user_id(harness, "admin2")
    results = await asyncio.gather(
        admin.patch(f"{USERS}/{id2}", json={"is_active": False, "confirm_password": ADMIN_PASSWORD}),
        admin2.patch(f"{USERS}/{id1}", json={"is_active": False, "confirm_password": "Admin-Two-Pass-1"}),
    )
    statuses = sorted(r.status_code for r in results)
    assert await harness.db.users.count_documents({"role": "ADMIN", "is_active": True}) == 1
    # One succeeds; the other is refused (last admin) or finds its own session already revoked.
    assert statuses[0] == 200 and statuses[1] in (401, 409)


async def test_user_change_and_audit_record_are_atomic(harness, admin, guard, monkeypatch):
    uid = await user_id(harness, "guard1")

    async def broken_record(*args, **kwargs):
        raise RuntimeError("audit store unavailable")
    monkeypatch.setattr(audit_module, "record", broken_record)
    r = await admin.patch(f"{USERS}/{uid}", json={"display_name": "Should Not Stick"})
    assert r.status_code == 500
    assert (await harness.db.users.find_one({"username": "guard1"}))["display_name"] != "Should Not Stick"


# ---------------------------------------------------------------- password reset & unlock
async def test_reset_password_requires_reauthentication(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    r = await admin.post(f"{USERS}/{uid}/reset-password", json={"new_password": "Reset-Guard-Pass-1"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "reauthentication_required"


async def test_reset_password_signs_out_unlocks_and_forces_a_change(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    for _ in range(5):
        await harness.client().login("guard1", "Wrong-Password-1")
    r = await admin.post(f"{USERS}/{uid}/reset-password",
                         json={"new_password": "Reset-Guard-Pass-1", "confirm_password": ADMIN_PASSWORD})
    assert r.status_code == 204
    assert (await guard.get(ME)).status_code == 401
    fresh = await harness.logged_in("guard1", "Reset-Guard-Pass-1")        # also proves the lock was cleared
    assert (await fresh.get(ME)).json()["user"]["must_change_password"] is True
    assert await harness.db.audit_logs.count_documents({"action": "PASSWORD_RESET"}) == 1


async def test_admin_cannot_reset_own_password_through_the_admin_endpoint(harness, admin):
    uid = await user_id(harness, "admin")
    r = await admin.post(f"{USERS}/{uid}/reset-password",
                         json={"new_password": "Other-Admin-Pass-1", "confirm_password": ADMIN_PASSWORD})
    assert r.status_code == 400


async def test_unlock(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    for _ in range(5):
        await harness.client().login("guard1", "Wrong-Password-1")
    assert (await admin.get(f"{USERS}/{uid}")).json()["locked"] is True
    r = await admin.post(f"{USERS}/{uid}/unlock")
    assert r.status_code == 200 and r.json()["locked"] is False
    assert (await harness.client().login("guard1", GUARD_PASSWORD)).status_code == 200
    assert await harness.db.audit_logs.count_documents({"action": "USER_UNLOCKED"}) == 1


async def test_no_password_ever_reaches_the_audit_log(harness, admin, guard):
    uid = await user_id(harness, "guard1")
    await admin.post(USERS, json=NEW_USER)
    await admin.post(f"{USERS}/{uid}/reset-password",
                     json={"new_password": "Reset-Guard-Pass-1", "confirm_password": ADMIN_PASSWORD})
    await admin.patch(f"{USERS}/{uid}", json={"role": "ADMIN", "confirm_password": ADMIN_PASSWORD})
    everything = str(await harness.db.audit_logs.find({}).to_list(None))
    for secret in (ADMIN_PASSWORD, GUARD_PASSWORD, "Temp-Guard-Pass-1", "Reset-Guard-Pass-1", "argon2"):
        assert secret not in everything


# ---------------------------------------------------------------- create-admin CLI
def run_cli(settings, *args, stdin=""):
    env = {**os.environ, "CG_MONGO_URI": TEST_MONGO_URI, "CG_MONGO_DB": settings.mongo_db,
           "CG_ENVIRONMENT": "test"}
    api_dir = Path(__file__).resolve().parents[1]
    return subprocess.run([sys.executable, "-m", "app.cli", *args], input=stdin, capture_output=True, text=True,
                          cwd=api_dir, env=env, timeout=60)


async def test_create_admin_cli(harness, settings):
    ok = run_cli(settings, "create-admin", "--username", "director", "--password-stdin", stdin="Chief-Admin-Pass-1\n")
    assert ok.returncode == 0, ok.stderr
    assert "Chief-Admin-Pass-1" not in ok.stdout + ok.stderr
    again = run_cli(settings, "create-admin", "--username", "DIRECTOR", "--password-stdin", stdin="Other-Pass-123\n")
    assert again.returncode == 2 and "already exists" in again.stderr
    weak = run_cli(settings, "create-admin", "--username", "boss", "--password-stdin", stdin="short\n")
    assert weak.returncode == 2 and "at least" in weak.stderr
    c = await harness.logged_in("director", "Chief-Admin-Pass-1")
    me = (await c.get(ME)).json()
    assert me["user"]["role"] == "ADMIN" and me["user"]["must_change_password"] is False
    entry = await harness.db.audit_logs.find_one({"action": "USER_CREATED"})
    assert entry["metadata"] == {"source": "cli"}
