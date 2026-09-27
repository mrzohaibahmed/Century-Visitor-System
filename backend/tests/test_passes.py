"""Visitor passes: issue, reissue, revoke, expiry, scan and QR check-out."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from app.core.security import hash_token
from app.services.passes import parse_qr
from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio


@pytest.fixture
async def inside(guard, directory):  # noqa: F811
    visitor = await new_visitor(guard)
    return (await check_in(guard, visitor["id"], directory)).json()


async def issue(client, visit):
    r = await client.post(f"/api/v1/visits/{visit['id']}/pass")
    assert r.status_code == 200, r.text
    return r.json()


async def scan(client, qr_text, action="resolve"):
    return await client.post(f"/api/v1/passes/{action}", json={"qr_text": qr_text})


# ---------------------------------------------------------------- issue
async def test_pass_contains_only_a_random_token(harness, guard, inside):
    issued = await issue(guard, inside)
    qr = issued["qr_text"]
    assert qr.startswith("CGP1:") and len(qr) == 5 + 64 and parse_qr(qr)
    for secret in (CNIC, CNIC.replace("-", ""), inside["visit_number"], inside["id"], "Ali", "0300"):
        assert secret not in qr
    stored = await harness.db.visits.find_one({"_id": ObjectId(inside["id"])})
    assert stored["pass"]["token_hash"] == hash_token(qr[5:]) and qr[5:] not in str(stored)
    record = await harness.db.audit_logs.find_one({"action": "PASS_ISSUED"})
    assert record["metadata"]["replaces_previous"] is False and qr[5:] not in str(record)


async def test_tokens_are_unique(guard, directory):  # noqa: F811
    tokens = set()
    for i in range(3):
        v = await new_visitor(guard, name=f"Person {chr(65 + i)}", number=f"35201-00000{i:02d}-1", phone=None)
        tokens.add((await issue(guard, (await check_in(guard, v["id"], directory)).json()))["qr_text"])
    assert len(tokens) == 3


async def test_badge_has_what_the_gate_needs_and_no_id_number(settings, guard, inside):
    badge = (await issue(guard, inside))["badge"]
    assert badge["organization"] == settings.organization_name
    assert badge["visitor_name"] == "Ali Khan" and badge["visit_number"] == inside["visit_number"]
    assert badge["host_name"] == "Sara Ahmed" and badge["department_name"] == "HR" and badge["gate_name"] == "Main Gate"
    assert badge["check_in_at"] and badge["valid_until"]
    text = str(badge)
    assert "35201" not in text and "0300" not in text and "phone" not in text and "identity" not in text


async def test_badge_print_is_recorded(harness, guard, inside):
    r = await guard.post(f"/api/v1/visits/{inside['id']}/badge-print")
    assert r.status_code == 204
    record = await harness.db.audit_logs.find_one({"action": "BADGE_PRINT_REQUESTED"})
    assert record["metadata"]["visit_number"] == inside["visit_number"]
    assert (await guard.post(f"/api/v1/visits/{'0' * 24}/badge-print")).status_code == 404


async def test_no_pass_for_a_visitor_who_left(guard, inside):
    await guard.post(f"/api/v1/visits/{inside['id']}/check-out")
    r = await guard.post(f"/api/v1/visits/{inside['id']}/pass")
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_checked_in"


# ---------------------------------------------------------------- scan and check-out
async def test_scanning_identifies_the_visit_and_changes_nothing(harness, guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    r = await scan(guard, qr)
    assert r.status_code == 200 and r.json()["status"] == "VALID"
    assert r.json()["visit"]["visit_number"] == inside["visit_number"]
    assert (await guard.get(f"/api/v1/visits/{inside['id']}")).json()["status"] == "CHECKED_IN"
    assert await harness.db.audit_logs.count_documents({"action": "VISIT_CHECKED_OUT"}) == 0


async def test_usb_scanners_may_change_case_and_add_whitespace(guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    assert (await scan(guard, f"  {qr.lower()}\r\n")).json()["status"] == "VALID"


async def test_check_out_with_a_pass_is_idempotent(harness, guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    first = await scan(guard, qr, "check-out")
    assert first.status_code == 200 and first.json()["already_checked_out"] is False
    assert first.json()["visit"]["checkout_method"] == "QR"
    again = await scan(guard, qr, "check-out")
    assert again.status_code == 200 and again.json()["already_checked_out"] is True
    after = await scan(guard, qr)
    assert after.json()["status"] == "CHECKED_OUT"                   # replay: shows who, does nothing
    records = await harness.db.audit_logs.find({"action": "VISIT_CHECKED_OUT"}).to_list(length=5)
    assert len(records) == 1 and records[0]["metadata"]["method"] == "QR"


async def test_concurrent_scans_record_one_departure(harness, admin, guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    results = await asyncio.gather(*(scan(c, qr, "check-out") for c in (admin, guard, admin, guard)))
    assert sorted(r.json()["already_checked_out"] for r in results) == [False, True, True, True]
    assert await harness.db.audit_logs.count_documents({"action": "VISIT_CHECKED_OUT"}) == 1


async def test_a_pass_cannot_be_used_after_the_visitor_comes_back(guard, directory, inside):  # noqa: F811
    old_qr = (await issue(guard, inside))["qr_text"]
    await scan(guard, old_qr, "check-out")
    again = (await check_in(guard, inside["visitor"]["id"], directory)).json()        # a new visit
    r = await scan(guard, old_qr, "check-out")
    assert r.json()["already_checked_out"] is True and r.json()["visit"]["id"] == inside["id"]
    assert (await guard.get(f"/api/v1/visits/{again['id']}")).json()["status"] == "CHECKED_IN"


@pytest.mark.parametrize("mutate", [
    lambda qr: qr[:-1] + ("0" if qr[-1] != "0" else "1"),        # one character changed
    lambda qr: qr[:20] + qr[21:] + "A",
    lambda qr: "CGP1:" + "0" * 64,
])
async def test_tampered_passes_match_nothing(harness, guard, inside, mutate):
    qr = (await issue(guard, inside))["qr_text"]
    r = await scan(guard, mutate(qr), "check-out")
    assert r.status_code == 404 and r.json()["error"]["code"] == "invalid_pass"
    assert (await guard.get(f"/api/v1/visits/{inside['id']}")).json()["status"] == "CHECKED_IN"
    record = await harness.db.audit_logs.find_one({"action": "PASS_REJECTED"})
    assert record["metadata"]["reason"] == "unknown" and record["result"] == "FAILURE"


@pytest.mark.parametrize("text", ["V-2026-000001", CNIC, "https://example.com", "CGP1:12345", "CGP2:" + "A" * 64])
async def test_other_codes_are_not_passes(guard, text):
    r = await scan(guard, text)
    assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_pass"


async def test_a_reprinted_badge_cancels_the_old_one(harness, guard, inside):
    old = (await issue(guard, inside))["qr_text"]
    new = (await issue(guard, inside))["qr_text"]
    assert old != new
    r = await scan(guard, old, "check-out")
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_replaced"
    assert (await scan(guard, new)).json()["status"] == "VALID"
    reissue = await harness.db.audit_logs.find_one({"action": "PASS_ISSUED", "metadata.replaces_previous": True})
    assert reissue is not None


async def test_a_revoked_pass_is_refused_but_the_visit_can_still_be_closed(harness, guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    r = await guard.post(f"/api/v1/visits/{inside['id']}/pass/revoke")
    assert r.status_code == 200
    assert (await guard.post(f"/api/v1/visits/{inside['id']}/pass/revoke")).status_code == 200    # idempotent
    assert await harness.db.audit_logs.count_documents({"action": "PASS_REVOKED"}) == 1
    refused = await scan(guard, qr, "check-out")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "pass_revoked"
    assert inside["visit_number"] in refused.json()["error"]["message"]
    by_number = await guard.post("/api/v1/visits/check-out", json={"visit_number": inside["visit_number"]})
    assert by_number.json()["visit"]["status"] == "CHECKED_OUT"


async def test_an_expired_pass_is_refused(harness, guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    await harness.db.visits.update_one({"_id": ObjectId(inside["id"])},
                                       {"$set": {"pass.expires_at": datetime.now(UTC) - timedelta(minutes=1)}})
    r = await scan(guard, qr, "check-out")
    assert r.status_code == 409 and r.json()["error"]["code"] == "pass_expired"
    assert (await guard.get(f"/api/v1/visits/{inside['id']}")).json()["status"] == "CHECKED_IN"
    assert (await harness.db.audit_logs.find_one({"action": "PASS_REJECTED"}))["metadata"]["reason"] == "expired"


async def test_pass_validity_follows_the_setting(settings, guard, inside):
    issued = await issue(guard, inside)
    expires = datetime.fromisoformat(issued["expires_at"])
    expected = datetime.now(UTC) + timedelta(hours=settings.pass_valid_hours)
    assert abs((expires - expected).total_seconds()) < 60


# ---------------------------------------------------------------- access
async def test_anonymous_and_forged_pass_requests_are_refused(harness, guard, inside):
    qr = (await issue(guard, inside))["qr_text"]
    anonymous = harness.client()
    visit = f"/api/v1/visits/{inside['id']}"
    for path, body in ((f"{visit}/pass", None), (f"{visit}/pass/revoke", None), (f"{visit}/badge-print", None),
                       ("/api/v1/passes/resolve", {"qr_text": qr}), ("/api/v1/passes/check-out", {"qr_text": qr})):
        assert (await anonymous.post(path, json=body)).status_code == 401, path
        assert (await guard.post_without_csrf(path, json=body)).status_code == 403, path
    assert (await guard.get(f"/api/v1/visits/{inside['id']}")).json()["status"] == "CHECKED_IN"


async def test_pass_details_never_appear_in_visit_responses(guard, inside):
    await issue(guard, inside)
    for path in (f"/api/v1/visits/{inside['id']}", "/api/v1/visits", "/api/v1/visits/active"):
        text = (await guard.get(path)).text
        assert "token" not in text and "pass" not in text, path
