"""Reports step 3: entry_denials. Refused entries are recorded for reporting, after (never instead of) the
security decision and its audit entries; a missing record is repaired by the idempotent backfill."""
import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import pyodbc
import pytest
from sqlalchemy.exc import IntegrityError

from app.repositories import entry_denials as denials_repo
from app.services import entry_denials as svc
from app.services import reports as reports_svc
from tests.conftest import new_record_id, raw_database_errors, record_id
from tests.test_users import run_cli
from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
REFUSAL = "Entry not permitted: Theft of property. Do not admit this visitor; inform the security supervisor."
LOOKUP = "/api/v1/visitors/lookup"
FIELDS = {"_id", "at", "reason", "source", "source_audit_id", "visitor_id", "visitor_name", "identifier_masked",
          "watchlist_id", "gate_id", "gate_name", "operator_id", "operator_username", "operator_name", "reason_code"}


async def ban(harness, number=CNIC, id_type="CNIC", **entry) -> dict:
    doc = {"identifier": f"{id_type}:{number}", "identity": {"type": id_type, "number": number},
           "reason": "Theft of property.", "is_active": True, "expires_at": None,
           "created_at": datetime.now(UTC),
           "created_by": (await harness.store.users.find_one({}))["_id"]} | entry      # an existing account
    doc["_id"] = (await harness.store.watchlist.insert_one(doc)).inserted_id
    return doc


async def denials(harness) -> list[dict]:
    return await harness.store.entry_denials.find().sort("_id", 1).to_list(length=100)


async def lookup(client, number=CNIC, id_type="CNIC"):
    return await client.get(LOOKUP, params={"id_type": id_type, "id_number": number})


def fail_denial_inserts(monkeypatch, error: Exception | None = None, delay: float | None = None):
    """Makes every entry_denials insert fail (or hang) with a driver error that quotes a CNIC, as a real
    schema refusal can; other tables are untouched."""
    async def insert(db, doc):
        if delay:
            await asyncio.sleep(delay)
        raise error or IntegrityError("INSERT INTO dbo.entry_denials ...", None, pyodbc.Error(
            "23000", "[23000] The INSERT statement conflicted with the CHECK constraint (value 35201-1234567-1). "
                     "(547) (SQLExecDirectW)"))
    monkeypatch.setattr(denials_repo, "insert", insert)


# ------------------------------------------------------------------------------------------ check-in
async def test_a_refused_check_in_is_recorded_once(harness, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    entry = await ban(harness)
    r = await check_in(guard, v["id"], directory)
    assert (r.status_code, r.json()["error"]["code"], r.json()["error"]["message"]) == (403, "entry_denied", REFUSAL)
    assert await harness.store.visits.count_documents({}) == 0
    match = await harness.store.audit_logs.find_one({"action": "WATCHLIST_MATCH"})
    assert await harness.store.audit_logs.count_documents({"action": "WATCHLIST_MATCH"}) == 1
    assert await harness.store.audit_logs.count_documents({"action": "VISIT_CHECKED_IN", "result": "DENIED",
                                                        "metadata.reason": "watchlist"}) == 1
    assert "context" not in match["metadata"]                  # the check-in audit entry is as before

    [d] = await denials(harness)
    guard_user = await harness.store.users.find_one({"username": "guard1"})
    assert set(d) == FIELDS
    assert d["source_audit_id"] == match["_id"] and d["at"] == match["timestamp"]
    assert (d["source"], d["reason"], d["reason_code"]) == ("check_in", "WATCHLIST", "OFFICIAL_MEETING")
    assert (d["visitor_id"], d["visitor_name"]) == (record_id(v["id"]), "Ali Khan")
    assert d["identifier_masked"] == "CNIC:***********67-1" and d["watchlist_id"] == entry["_id"]
    assert (d["gate_id"], d["gate_name"]) == (record_id(directory["gate"]["id"]), "Main Gate")
    assert (d["operator_id"], d["operator_username"], d["operator_name"]) == (guard_user["_id"], "guard1", "Guard1")


async def test_every_refused_attempt_counts(harness, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    for _ in range(2):
        assert (await check_in(guard, v["id"], directory)).status_code == 403
    assert len(await denials(harness)) == 2


async def test_the_operator_and_gate_cannot_come_from_the_request(harness, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    r = await guard.post("/api/v1/visits", json={"visitor_id": v["id"], "host_id": directory["host"]["id"],
                                                 "reason_code": "INTERVIEW", "operator_id": str(new_record_id()),
                                                 "gate_id": str(new_record_id())})
    assert r.status_code == 422 and await denials(harness) == []    # unknown fields are refused outright


# ------------------------------------------------------------------------------------------ lookup
async def test_a_blocked_lookup_is_recorded_once_and_answers_as_before(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    entry = await ban(harness)
    r = await lookup(guard, "3520112345671")                         # any format
    assert r.status_code == 200
    body = r.json()
    assert body["screening"] == {"status": "BLOCKED", "reason": "Theft of property."}
    # The same answer as the details view gives (which records nothing).
    assert body == (await guard.get(f"/api/v1/visitors/{v['id']}")).json()

    [d] = await denials(harness)
    match = await harness.store.audit_logs.find_one({"action": "WATCHLIST_MATCH"})
    guard_user = await harness.store.users.find_one({"username": "guard1"})
    assert match["metadata"]["context"] == "lookup" and match["metadata"]["watchlist_id"] == entry["_id"]
    assert await harness.store.audit_logs.count_documents({"action": "VISITOR_LOOKUP"}) == 1      # as before
    assert await harness.store.audit_logs.count_documents({"action": "VISIT_CHECKED_IN"}) == 0
    assert (d["source"], d["reason"], d["reason_code"]) == ("lookup", "WATCHLIST", None)
    assert d["source_audit_id"] == match["_id"] and d["at"] == match["timestamp"]
    assert (d["visitor_id"], d["watchlist_id"]) == (record_id(v["id"]), entry["_id"])
    assert (d["operator_id"], d["operator_name"]) == (guard_user["_id"], "Guard1")
    assert d["gate_id"] == record_id(directory["gate"]["id"])        # the only active gate
    assert await harness.store.visits.count_documents({}) == 0


async def test_a_blocked_lookup_without_a_gate_is_still_recorded(harness, admin, guard, directory):  # noqa: F811
    await admin.post("/api/v1/gates", json={"name": "East Gate"})   # two gates: none chosen by this session
    await new_visitor(guard)
    await ban(harness)
    session_before = await harness.store.sessions.find_one({"user_id": (await harness.store.users.find_one(
        {"username": "guard1"}))["_id"]})
    assert (await lookup(guard)).json()["screening"]["status"] == "BLOCKED"
    [d] = await denials(harness)
    assert (d["gate_id"], d["gate_name"]) == (None, None)
    session_after = await harness.store.sessions.find_one({"_id": session_before["_id"]})
    assert session_after.get("gate_id") == session_before.get("gate_id")   # the lookup chose no gate


async def test_each_blocked_lookup_counts(harness, guard, directory):  # noqa: F811
    await new_visitor(guard)
    await ban(harness)
    for _ in range(3):
        await lookup(guard)
    assert [d["source"] for d in await denials(harness)] == ["lookup"] * 3


# ------------------------------------------------------------------------------------------ not denials
async def test_nothing_else_is_recorded_as_a_denial(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    assert (await lookup(guard)).json()["screening"]["status"] == "CLEAR"          # ordinary lookup
    visit = (await check_in(guard, v["id"], directory)).json()                     # normal check-in
    assert (await check_in(guard, v["id"], directory)).status_code == 409          # already inside
    assert (await guard.post(f"/api/v1/visits/{visit['id']}/check-out")).status_code == 200
    assert (await check_in(guard, v["id"], directory, reason_code="OTHER")).status_code == 422   # validation
    assert (await guard.get("/api/v1/users")).status_code == 403                    # access denied
    assert (await guard.get("/api/v1/reports/overview")).status_code == 403
    await ban(harness)
    assert (await admin.get(f"/api/v1/visitors/{v['id']}")).json()["screening"]["status"] == "BLOCKED"  # details
    assert await denials(harness) == []


async def test_a_gate_required_refusal_is_not_a_denial(harness, admin, guard, directory):  # noqa: F811
    await admin.post("/api/v1/gates", json={"name": "East Gate"})
    v = await new_visitor(guard)
    await ban(harness)
    r = await check_in(guard, v["id"], directory)
    assert (r.status_code, r.json()["error"]["code"]) == (409, "gate_required")    # unchanged: gate first
    assert await denials(harness) == []


@pytest.mark.parametrize("entry", [{"is_active": False}, {"expires_at": datetime.now(UTC) - timedelta(days=1)}])
async def test_inactive_or_expired_bans_record_nothing(harness, guard, directory, entry):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness, **entry)
    assert (await lookup(guard)).json()["screening"]["status"] == "CLEAR"
    assert (await check_in(guard, v["id"], directory)).status_code == 201
    assert await denials(harness) == []


# ------------------------------------------------------------------------------------------ privacy
async def test_denials_hold_nothing_private(harness, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    await check_in(guard, v["id"], directory, reason_code="OTHER", reason_note="Meeting about a private matter")
    await lookup(guard)
    text = str(await denials(harness))
    for secret in (CNIC, CNIC.replace("-", ""), "1234567", "03001234567", "0300", "private matter", "Laptop",
                   "LEA1234", "token", "password", "session", "photo", "belongings", "reason_note"):
        assert secret not in text, secret
    assert all(set(d) == FIELDS for d in await denials(harness))


async def test_short_identity_numbers_are_masked_more_strictly_than_the_audit(harness, guard, directory):  # noqa: F811
    v = await new_visitor(guard, number="AB1", id_type="OTHER")
    await ban(harness, number="AB1", id_type="OTHER")
    await check_in(guard, v["id"], directory)
    [d] = await denials(harness)
    match = await harness.store.audit_logs.find_one({"action": "WATCHLIST_MATCH"})
    assert d["identifier_masked"] == "OTHER:**1"
    assert match["metadata"]["identifier"] == "OTHER:AB1"            # the audit masking is unchanged (D5)


# ------------------------------------------------------------------------------------------ failures
@pytest.mark.parametrize("failure", ["error", "timeout", "bug"])
async def test_a_failed_reporting_write_never_lets_anyone_in(harness, guard, directory, monkeypatch, caplog,  # noqa: F811
                                                             failure):
    v = await new_visitor(guard)
    await ban(harness)
    if failure == "error":
        fail_denial_inserts(monkeypatch)
    elif failure == "timeout":
        monkeypatch.setattr(svc, "RECORD_TIMEOUT_SECONDS", 0.2)
        fail_denial_inserts(monkeypatch, delay=5)
    else:
        def broken(_identity):
            raise ValueError("unexpected")
        monkeypatch.setattr(svc, "masked_identifier", broken)
    caplog.set_level(logging.INFO)

    r = await check_in(guard, v["id"], directory)
    assert (r.status_code, r.json()["error"]["code"], r.json()["error"]["message"]) == (403, "entry_denied", REFUSAL)
    lookup_answer = (await lookup(guard)).json()
    assert lookup_answer["screening"]["status"] == "BLOCKED"                  # the lookup answers as before
    assert await harness.store.visits.count_documents({}) == 0
    assert await harness.store.audit_logs.count_documents({"action": "WATCHLIST_MATCH"}) == 2
    assert await harness.store.audit_logs.count_documents({"action": "VISIT_CHECKED_IN", "result": "DENIED"}) == 1
    assert await denials(harness) == []
    failures = [rec.getMessage() for rec in caplog.records if "Entry denial not recorded" in rec.getMessage()]
    assert len(failures) == 2 and "backfill-entry-denials" in failures[0]
    # Everything the application logged, tracebacks included (the test client's own request log is not ours).
    logged = "\n".join(caplog.handler.format(rec) for rec in caplog.records if rec.name.startswith("app"))
    assert "Entry denial not recorded" in logged
    for secret in (CNIC, "1234567", "Ali Khan", "03001234567"):
        assert secret not in logged, secret

    # The backfill repairs both missing documents from their audit entries.
    monkeypatch.undo()
    report = await svc.backfill_from_audit(harness.db)
    assert (report.created, report.incomplete) == (2, 0)
    assert sorted(d["source"] for d in await denials(harness)) == ["audit_backfill", "audit_backfill"]


# ------------------------------------------------------------------------------------------ backfill
async def _audit_match(harness, *, at=None, **fields) -> dict:
    entry = {"timestamp": at or datetime.now(UTC), "action": "WATCHLIST_MATCH", "result": "SUCCESS",
             "actor": {"user_id": new_record_id(), "username": "oldguard", "role": "GUARD"},
             "resource": {"type": "visitor", "id": new_record_id()},
             "metadata": {"watchlist_id": new_record_id(), "gate_id": new_record_id(),
                          "identifier": "CNIC:***********67-1"}}
    entry |= fields
    entry["_id"] = (await harness.store.audit_logs.insert_one(entry)).inserted_id
    return entry


async def test_backfill_copies_only_what_was_recorded_and_is_repeatable(harness):
    entries = [await _audit_match(harness, at=datetime(2026, 9, d, 8, tzinfo=UTC)) for d in (1, 2, 3)]
    first = await svc.backfill_from_audit(harness.db)
    assert first.as_dict() == {"scanned": 3, "created": 3, "already_present": 0, "incomplete": 0, "skipped": 0,
                               "failed": 0}
    docs = await denials(harness)
    for d, e in zip(docs, entries, strict=True):
        assert d["source_audit_id"] == e["_id"] and d["at"] == e["timestamp"] and d["source"] == "audit_backfill"
        assert (d["visitor_id"], d["watchlist_id"], d["gate_id"]) == (
            e["resource"]["id"], e["metadata"]["watchlist_id"], e["metadata"]["gate_id"])
        assert (d["operator_id"], d["operator_username"]) == (e["actor"]["user_id"], "oldguard")
        # Never recorded, so never guessed: no names, no purpose.
        assert (d["visitor_name"], d["gate_name"], d["operator_name"], d["reason_code"]) == (None,) * 4
    second = await svc.backfill_from_audit(harness.db)
    assert (second.scanned, second.created, second.already_present) == (3, 0, 3)
    assert len(await denials(harness)) == 3


async def test_backfill_and_runtime_records_never_duplicate(harness, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    await check_in(guard, v["id"], directory)
    await lookup(guard)
    report = await svc.backfill_from_audit(harness.db)
    assert (report.created, report.already_present) == (0, 2)
    assert sorted(d["source"] for d in await denials(harness)) == ["check_in", "lookup"]


async def test_backfill_never_changes_an_existing_document(harness):
    entry = await _audit_match(harness)
    await harness.store.entry_denials.insert_one({"at": entry["timestamp"], "reason": "WATCHLIST", "source": "check_in",
                                               "source_audit_id": entry["_id"], "visitor_name": "As recorded"})
    await svc.backfill_from_audit(harness.db)
    [d] = await denials(harness)
    assert (d["source"], d["visitor_name"]) == ("check_in", "As recorded")


async def test_backfill_handles_incomplete_audit_entries(harness):
    await _audit_match(harness, metadata={}, resource={"type": "visitor"})              # ids missing
    await _audit_match(harness, metadata={"identifier": "OTHER:AB1", "gate_id": "not-an-id"}, actor={})
    await _audit_match(harness)
    report = await svc.backfill_from_audit(harness.db)
    assert (report.scanned, report.created, report.incomplete, report.failed) == (3, 3, 2, 0)
    docs = await denials(harness)
    assert docs[0]["visitor_id"] is None and docs[0]["identifier_masked"] is None
    assert docs[1]["identifier_masked"] == "OTHER:**1" and docs[1]["gate_id"] is None      # re-masked; bad id: null
    assert docs[1]["operator_id"] is None and docs[1]["operator_username"] is None


def test_an_entry_without_a_timestamp_is_skipped_not_guessed():
    assert svc.from_audit({"_id": new_record_id(), "action": "WATCHLIST_MATCH"}) == (None, False)


async def test_a_lookup_refusal_without_a_gate_is_complete(harness):
    await _audit_match(harness, metadata={"watchlist_id": new_record_id(), "gate_id": None,
                                          "identifier": "CNIC:***********67-1", "context": "lookup"})
    assert (await svc.backfill_from_audit(harness.db)).incomplete == 0


async def test_concurrent_backfills_create_each_document_once(harness):
    for _ in range(20):
        await _audit_match(harness)
    reports = await asyncio.gather(*(svc.backfill_from_audit(harness.db) for _ in range(4)))
    assert sum(r.created for r in reports) == 20
    assert all(r.created + r.already_present == 20 and r.failed == 0 for r in reports)
    assert await harness.store.entry_denials.count_documents({}) == 20


async def test_the_backfill_command(harness, settings):
    """python -m app.cli backfill-entry-denials, against the test database (migrate first, as an operator would)."""
    assert run_cli(settings, "migrate").returncode == 0
    await _audit_match(harness, metadata={})
    first = run_cli(settings, "backfill-entry-denials")
    assert first.returncode == 0, first.stderr
    report = json.loads(first.stdout)
    assert (report["created"], report["incomplete"], report["database"]) == (1, 1, settings.mssql_database)
    again = run_cli(settings, "backfill-entry-denials")
    assert again.returncode == 0 and json.loads(again.stdout)["created"] == 0
    assert run_cli(settings, "migrate").returncode == 0                # migrating again changes nothing
    assert await harness.store.entry_denials.count_documents({}) == 1


# ------------------------------------------------------------------------------------------ reports
async def test_security_counts_read_the_denials(harness, guard, directory):  # noqa: F811
    """Since step 4 the counts come from entry_denials: a check-in refusal and a lookup refusal count
    once each in both (under audit_logs the lookup counted as a match only: 1 and 2)."""
    v = await new_visitor(guard)
    await ban(harness)
    await check_in(guard, v["id"], directory)
    await lookup(guard)
    now = datetime.now(UTC)
    counts = await reports_svc.security_counts(harness.db, now - timedelta(hours=1), now + timedelta(minutes=1))
    assert (counts.denied_entries, counts.watchlist_matches) == (2, 2)
    assert await harness.store.entry_denials.count_documents({}) == 2


def test_no_route_exposes_denials_yet():
    from app.api.v1.router import api_router
    assert not [r.path for r in api_router.routes if "denial" in getattr(r, "path", "")]


# ------------------------------------------------------------------------------------------ schema
async def test_the_table_validates_and_deduplicates(harness):
    """One record per audit entry, only known reasons, sources and purposes, never without its audit entry."""
    duplicate, rejected = raw_database_errors()
    base = {"at": datetime.now(UTC), "reason": "WATCHLIST", "source": "check_in", "source_audit_id": new_record_id()}
    await harness.store.entry_denials.insert_one(dict(base))
    with pytest.raises(duplicate):
        await harness.store.entry_denials.insert_one(dict(base))
    for bad in ({"source": "guess"}, {"reason": "OTHER"}, {"source_audit_id": None}, {"reason_code": "SHOPPING"}):
        with pytest.raises(rejected):
            await harness.store.entry_denials.insert_one(base | {"source_audit_id": new_record_id()} | bad)
    assert await harness.store.entry_denials.count_documents({}) == 1
