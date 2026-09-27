"""Check-in, check-out, active list and visit history."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from tests.test_visitors import CNIC, new_visitor

pytestmark = pytest.mark.anyio


@pytest.fixture
async def directory(admin):
    gate = (await admin.post("/api/v1/gates", json={"name": "Main Gate"})).json()
    dep = (await admin.post("/api/v1/departments", json={"name": "HR"})).json()
    other_dep = (await admin.post("/api/v1/departments", json={"name": "Stores"})).json()
    host = (await admin.post("/api/v1/hosts", json={"name": "Sara Ahmed", "department_id": dep["id"]})).json()
    return {"gate": gate, "dep": dep, "other_dep": other_dep, "host": host}


def check_in_body(visitor_id, directory, **overrides):
    body = {"visitor_id": visitor_id, "host_id": directory["host"]["id"], "reason_code": "OFFICIAL_MEETING",
            "vehicle_registration": "lea 1234", "belongings": ["Laptop"]}
    body.update(overrides)
    return body


async def check_in(client, visitor_id, directory, **overrides):
    return await client.post("/api/v1/visits", json=check_in_body(visitor_id, directory, **overrides))


# ---------------------------------------------------------------- check-in
async def test_check_in(harness, guard, directory):
    v = await new_visitor(guard)
    r = await check_in(guard, v["id"], directory)
    assert r.status_code == 201, r.text
    visit = r.json()
    year = datetime.now(UTC).year
    assert visit["visit_number"] == f"V-{year}-000001" and visit["status"] == "CHECKED_IN"
    assert visit["visitor"]["name"] == "Ali Khan" and visit["host"]["name"] == "Sara Ahmed"
    assert visit["department"]["name"] == "HR"                    # taken from the host
    assert visit["gate"]["name"] == "Main Gate"                   # taken from the session, not the request
    assert visit["checked_in_by"]["name"] == "Guard1" and visit["vehicle_registration"] == "LEA1234"
    entry = await harness.db.audit_logs.find_one({"action": "VISIT_CHECKED_IN", "result": "SUCCESS"})
    assert entry["metadata"]["visit_number"] == visit["visit_number"]


async def test_client_cannot_choose_gate_operator_or_status(guard, directory):
    v = await new_visitor(guard)
    for extra in ({"gate_id": directory["gate"]["id"]}, {"checked_in_by": "x"}, {"status": "CHECKED_OUT"}):
        r = await check_in(guard, v["id"], directory, **extra)
        assert r.status_code == 422, extra


async def test_a_visitor_can_only_be_inside_once(guard, directory):
    v = await new_visitor(guard)
    first = await check_in(guard, v["id"], directory)
    second = await check_in(guard, v["id"], directory)
    assert second.status_code == 409 and second.json()["error"]["code"] == "already_inside"
    assert first.json()["visit_number"] in second.json()["error"]["message"]


async def test_two_gates_checking_in_the_same_person_at_once(harness, admin, guard, directory):
    v = await new_visitor(guard)
    results = await asyncio.gather(*(check_in(c, v["id"], directory) for c in (admin, guard, admin, guard)))
    assert sorted(r.status_code for r in results) == [201, 409, 409, 409]
    assert await harness.db.visits.count_documents({"status": "CHECKED_IN"}) == 1


async def test_visit_numbers_are_unique_and_gap_free_under_load(harness, guard, directory):
    visitors = [await new_visitor(guard, name=f"Person {chr(65 + i)}", number=f"35201-00000{i:02d}-1", phone=None)
                for i in range(8)]
    results = await asyncio.gather(*(check_in(guard, v["id"], directory) for v in visitors))
    numbers = sorted(r.json()["visit_number"] for r in results)
    year = datetime.now(UTC).year
    assert numbers == [f"V-{year}-{i:06d}" for i in range(1, 9)]


async def test_watchlist_blocks_entry_in_any_id_format(harness, guard, directory):
    v = await new_visitor(guard, number="3520112345671")
    await harness.db.watchlist.insert_one({
        "identifier": f"CNIC:{CNIC}", "identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft of property.",
        "is_active": True, "expires_at": None, "created_by": ObjectId(), "created_at": datetime.now(UTC)})
    r = await check_in(guard, v["id"], directory)
    assert r.status_code == 403 and r.json()["error"]["code"] == "entry_denied"
    assert "Theft of property." in r.json()["error"]["message"]
    assert await harness.db.visits.count_documents({}) == 0
    match = await harness.db.audit_logs.find_one({"action": "WATCHLIST_MATCH"})
    assert match["actor"]["username"] == "guard1" and "1234567" not in str(match)
    assert await harness.db.audit_logs.count_documents({"action": "VISIT_CHECKED_IN", "result": "DENIED"}) == 1


@pytest.mark.parametrize("entry", [{"is_active": False, "expires_at": None},
                                   {"is_active": True, "expires_at": datetime.now(UTC) - timedelta(days=1)}])
async def test_inactive_or_expired_bans_do_not_block(harness, guard, directory, entry):
    v = await new_visitor(guard)
    await harness.db.watchlist.insert_one({
        "identifier": f"CNIC:{CNIC}", "identity": {"type": "CNIC", "number": CNIC}, "reason": "Old.",
        "created_by": ObjectId(), "created_at": datetime.now(UTC), **entry})
    assert (await check_in(guard, v["id"], directory)).status_code == 201


async def test_unlisted_host_is_allowed_and_flagged(guard, directory):
    v = await new_visitor(guard)
    r = await check_in(guard, v["id"], directory, host_id=None, unlisted_host_name="Imran Ali",
                       department_id=directory["other_dep"]["id"])
    assert r.status_code == 201
    assert r.json()["host"] == {"id": None, "name": "Imran Ali"} and r.json()["host_unlisted"] is True


@pytest.mark.parametrize("overrides,code", [
    ({"host_id": None}, 422),                                                   # no host at all
    ({"unlisted_host_name": "Imran Ali"}, 422),                                 # both
    ({"reason_code": "OTHER"}, 422),                                            # other without a note
    ({"reason_code": "PARTY"}, 422),
    ({"vehicle_registration": "LE@1234"}, 422),
    ({"belongings": ["x"] * 11}, 422),
])
async def test_invalid_check_ins(guard, directory, overrides, code):
    v = await new_visitor(guard)
    assert (await check_in(guard, v["id"], directory, **overrides)).status_code == code


async def test_unlisted_host_needs_a_department(guard, directory):
    v = await new_visitor(guard)
    r = await check_in(guard, v["id"], directory, host_id=None, unlisted_host_name="Imran Ali")
    assert r.status_code == 422 and r.json()["error"]["code"] == "department_required"


async def test_inactive_host_cannot_be_visited(admin, guard, directory):
    await admin.patch(f"/api/v1/hosts/{directory['host']['id']}", json={"is_active": False})
    v = await new_visitor(guard)
    assert (await check_in(guard, v["id"], directory)).status_code == 409


async def test_check_in_needs_a_gate(harness, admin, guard):
    dep = (await admin.post("/api/v1/departments", json={"name": "HR"})).json()
    host = (await admin.post("/api/v1/hosts", json={"name": "Sara Ahmed", "department_id": dep["id"]})).json()
    v = await new_visitor(guard)
    body = {"visitor_id": v["id"], "host_id": host["id"], "reason_code": "INTERVIEW"}
    r = await guard.post("/api/v1/visits", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "no_gate_configured"
    await admin.post("/api/v1/gates", json={"name": "Main Gate"})
    await admin.post("/api/v1/gates", json={"name": "East Gate"})
    r = await guard.post("/api/v1/visits", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "gate_required"


# ---------------------------------------------------------------- check-out
async def test_check_out_is_idempotent_and_audited_once(harness, guard, directory):
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    first = await guard.post(f"/api/v1/visits/{visit['id']}/check-out")
    second = await guard.post(f"/api/v1/visits/{visit['id']}/check-out")
    assert first.json()["already_checked_out"] is False and first.json()["visit"]["status"] == "CHECKED_OUT"
    assert first.json()["visit"]["checkout_method"] == "MANUAL" and first.json()["visit"]["checkout_gate"]["name"]
    assert second.status_code == 200 and second.json()["already_checked_out"] is True
    assert second.json()["visit"]["check_out_at"] == first.json()["visit"]["check_out_at"]
    assert await harness.db.audit_logs.count_documents({"action": "VISIT_CHECKED_OUT"}) == 1


async def test_concurrent_check_outs_record_one_departure(harness, admin, guard, directory):
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    results = await asyncio.gather(*(c.post(f"/api/v1/visits/{visit['id']}/check-out") for c in (admin, guard, admin)))
    assert sorted(r.json()["already_checked_out"] for r in results) == [False, True, True]
    assert await harness.db.audit_logs.count_documents({"action": "VISIT_CHECKED_OUT"}) == 1


async def test_check_out_by_visit_number_or_id_number(guard, directory):
    a = await new_visitor(guard)
    b = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2")
    va = (await check_in(guard, a["id"], directory)).json()
    await check_in(guard, b["id"], directory)
    by_number = await guard.post("/api/v1/visits/check-out", json={"visit_number": va["visit_number"].lower()})
    assert by_number.status_code == 200 and by_number.json()["visit"]["checkout_method"] == "VISIT_NUMBER"
    by_id = await guard.post("/api/v1/visits/check-out", json={"identity": {"type": "CNIC", "number": "3520176543212"}})
    assert by_id.status_code == 200 and by_id.json()["visit"]["checkout_method"] == "ID_NUMBER"
    again = await guard.post("/api/v1/visits/check-out", json={"identity": {"type": "CNIC", "number": "3520176543212"}})
    assert again.status_code == 404 and again.json()["error"]["code"] == "not_inside"


@pytest.mark.parametrize("body", [{}, {"visit_number": "12345"}, {"visit_number": "V-2026-000001",
                                                                  "identity": {"type": "CNIC", "number": CNIC}}])
async def test_invalid_check_out_lookups(guard, body):
    assert (await guard.post("/api/v1/visits/check-out", json=body)).status_code == 422


async def test_visitor_can_come_back_after_leaving(guard, directory):
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    await guard.post(f"/api/v1/visits/{visit['id']}/check-out")
    assert (await check_in(guard, v["id"], directory)).status_code == 201


async def test_unknown_visits_are_404(guard):
    for path in ("/api/v1/visits/nope", f"/api/v1/visits/{'0' * 24}"):
        assert (await guard.get(path)).status_code == 404
        assert (await guard.post(f"{path}/check-out")).status_code == 404


# ---------------------------------------------------------------- lists
async def test_active_list(guard, directory):
    a = await new_visitor(guard)
    b = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2")
    va = (await check_in(guard, a["id"], directory)).json()
    await check_in(guard, b["id"], directory)
    await guard.post(f"/api/v1/visits/{va['id']}/check-out")
    active = (await guard.get("/api/v1/visits/active")).json()
    assert active["total"] == 1 and [i["visitor"]["name"] for i in active["items"]] == ["Alia Noor"]
    lookup = await guard.get("/api/v1/visitors/lookup", params={"id_type": "CNIC", "id_number": "35201-7654321-2"})
    assert lookup.json()["visitor"]["active_visit"]["gate_name"] == "Main Gate"


async def test_history_filters_and_search(harness, guard, directory):
    a = await new_visitor(guard)
    b = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2")
    va = (await check_in(guard, a["id"], directory)).json()
    vb = (await check_in(guard, b["id"], directory, host_id=None, unlisted_host_name="Imran Ali",
                         department_id=directory["other_dep"]["id"])).json()
    await guard.post(f"/api/v1/visits/{va['id']}/check-out")

    async def numbers(**params):
        r = await guard.get("/api/v1/visits", params=params)
        assert r.status_code == 200, r.text
        return [i["visit_number"] for i in r.json()["items"]]

    assert await numbers() == [vb["visit_number"], va["visit_number"]]          # newest first
    assert await numbers(status="CHECKED_OUT") == [va["visit_number"]]
    assert await numbers(department_id=directory["other_dep"]["id"]) == [vb["visit_number"]]
    assert await numbers(host_id=directory["host"]["id"]) == [va["visit_number"]]
    assert await numbers(q="alia") == [vb["visit_number"]]
    assert await numbers(q="3520112345671") == [va["visit_number"]]
    assert await numbers(q=va["visit_number"].lower()) == [va["visit_number"]]
    assert "pass" not in (await guard.get("/api/v1/visits")).text


async def test_date_filters_use_the_organisation_time_zone(harness, guard, directory):
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    # 20:30 UTC on 24 Sept is 01:30 on 25 Sept in Asia/Karachi (UTC+5).
    await harness.db.visits.update_one({"_id": ObjectId(visit["id"])},
                                       {"$set": {"check_in_at": datetime(2026, 9, 24, 20, 30, tzinfo=UTC)}})
    on_25 = (await guard.get("/api/v1/visits", params={"from": "2026-09-25", "to": "2026-09-25"})).json()["items"]
    on_24 = (await guard.get("/api/v1/visits", params={"from": "2026-09-24", "to": "2026-09-24"})).json()["items"]
    assert len(on_25) == 1 and on_24 == []


async def test_history_pages_without_repeats(guard, directory):
    ids = []
    for i in range(5):
        v = await new_visitor(guard, name=f"Person {chr(65 + i)}", number=f"35201-00000{i:02d}-1", phone=None)
        ids.append((await check_in(guard, v["id"], directory)).json()["visit_number"])
    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await guard.get("/api/v1/visits", params=params)).json()
        seen += [i["visit_number"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == list(reversed(ids))


async def test_visitor_history(guard, directory):
    v = await new_visitor(guard)
    first = (await check_in(guard, v["id"], directory)).json()
    await guard.post(f"/api/v1/visits/{first['id']}/check-out")
    second = (await check_in(guard, v["id"], directory)).json()
    r = await guard.get(f"/api/v1/visitors/{v['id']}/visits")
    assert [i["visit_number"] for i in r.json()["items"]] == [second["visit_number"], first["visit_number"]]


async def test_anonymous_requests_are_rejected(harness):
    c = harness.client()
    for method, path in (("GET", "/api/v1/visits"), ("GET", "/api/v1/visits/active"), ("POST", "/api/v1/visits"),
                         ("GET", "/api/v1/visitors?q=ali"), ("POST", "/api/v1/visitors")):
        assert (await c.request(method, path, json={})).status_code == 401, path
