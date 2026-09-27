"""Gates, departments, hosts and the session's gate."""
import pytest

from tests.conftest import GUARD_PASSWORD

pytestmark = pytest.mark.anyio


async def test_guards_read_but_cannot_change_the_directory(harness, admin, guard):
    await admin.post("/api/v1/gates", json={"name": "Main Gate"})
    assert (await guard.get("/api/v1/gates")).status_code == 200
    for path, body in (("/api/v1/gates", {"name": "X"}), ("/api/v1/departments", {"name": "X"}),
                       ("/api/v1/hosts", {"name": "Ali Khan"})):
        r = await guard.post(path, json=body)
        assert r.status_code == 403, path


async def test_create_and_list_gate_department_host(admin):
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate", "location": "North"})).json()
    dep = (await admin.post("/api/v1/departments",
                            json={"name": "HR", "notification_email": "HR@Example.com"})).json()
    host = (await admin.post("/api/v1/hosts", json={"name": "  sara   ahmed ", "email": "sara@example.com",
                                                    "phone": "0300-1234567", "department_id": dep["id"]})).json()
    assert gate["name"] == "Main Gate" and dep["notification_email"] == "hr@example.com"
    assert host["name"] == "sara ahmed" and host["phone"] == "03001234567" and host["department_name"] == "HR"
    assert [h["name"] for h in (await admin.get("/api/v1/hosts?q=SAR")).json()] == ["sara ahmed"]
    assert (await admin.get("/api/v1/hosts?q=zz")).json() == []


@pytest.mark.parametrize("path", ["/api/v1/gates", "/api/v1/departments"])
async def test_names_are_unique_ignoring_case(admin, path):
    await admin.post(path, json={"name": "Security"})
    r = await admin.post(path, json={"name": "SECURITY"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "name_taken"


async def test_deactivated_entries_are_hidden_from_pickers(admin, guard):
    dep = (await admin.post("/api/v1/departments", json={"name": "Stores"})).json()
    await admin.patch(f"/api/v1/departments/{dep['id']}", json={"is_active": False})
    assert (await guard.get("/api/v1/departments")).json() == []
    # guards cannot ask for inactive entries; admins can
    assert (await guard.get("/api/v1/departments?include_inactive=true")).json() == []
    assert [d["name"] for d in (await admin.get("/api/v1/departments?include_inactive=true")).json()] == ["Stores"]


async def test_host_department_must_exist_and_be_active(admin):
    dep = (await admin.post("/api/v1/departments", json={"name": "Stores"})).json()
    await admin.patch(f"/api/v1/departments/{dep['id']}", json={"is_active": False})
    assert (await admin.post("/api/v1/hosts", json={"name": "Ali Khan", "department_id": dep["id"]})).status_code == 409
    missing = "0" * 24
    assert (await admin.post("/api/v1/hosts", json={"name": "Ali Khan", "department_id": missing})).status_code == 404


@pytest.mark.parametrize("body", [{"name": ""}, {"name": "Main", "is_active": False}, {"name": "Main", "extra": 1}])
async def test_invalid_gate_bodies(admin, body):
    assert (await admin.post("/api/v1/gates", json=body)).status_code == 422


async def test_directory_changes_are_audited(harness, admin):
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()
    await admin.patch(f"/api/v1/gates/{gate['id']}", json={"name": "North Gate"})
    updated = await harness.db.audit_logs.find_one({"action": "GATE_UPDATED"})
    assert updated["changes"]["name"] == {"from": "Main Gate", "to": "North Gate"}
    assert await harness.db.audit_logs.count_documents({"action": "GATE_CREATED"}) == 1


# ---------------------------------------------------------------- session gate
async def test_single_gate_is_assigned_automatically(harness, admin):
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()
    await harness.create_user("guard1", GUARD_PASSWORD)
    me = (await harness.client().login("guard1", GUARD_PASSWORD)).json()
    assert me["session"]["gate"] == {"id": gate["id"], "name": "Main Gate"}
    assert me["session"]["gate_selection_required"] is False


async def test_with_several_gates_the_guard_chooses_one(harness, admin):
    await admin.post("/api/v1/gates", json={"name": "Main Gate"})
    east = (await admin.post("/api/v1/gates", json={"name": "East Gate"})).json()
    await harness.create_user("guard1", GUARD_PASSWORD)
    guard = await harness.logged_in("guard1", GUARD_PASSWORD)
    me = (await guard.get("/api/v1/auth/me")).json()
    assert me["session"]["gate"] is None and me["session"]["gate_selection_required"] is True
    r = await guard.put("/api/v1/auth/session/gate", json={"gate_id": east["id"]})
    assert r.status_code == 200 and r.json()["session"]["gate"]["name"] == "East Gate"
    assert await harness.db.audit_logs.count_documents({"action": "GATE_SELECTED"}) == 1


async def test_inactive_or_unknown_gates_cannot_be_selected(admin, guard):
    gate = (await admin.post("/api/v1/gates", json={"name": "Old Gate"})).json()
    await admin.post("/api/v1/gates", json={"name": "Main Gate"})
    await admin.patch(f"/api/v1/gates/{gate['id']}", json={"is_active": False})
    assert (await guard.put("/api/v1/auth/session/gate", json={"gate_id": gate["id"]})).status_code == 404
    assert (await guard.put("/api/v1/auth/session/gate", json={"gate_id": "nonsense"})).status_code == 422
