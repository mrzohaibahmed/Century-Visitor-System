"""Reports step 4: the overview's security counts come from entry_denials only (never audit_logs too)."""
from datetime import UTC, date, datetime, timedelta

import pytest
from bson import ObjectId

from app.services import entry_denials as denials_svc
from app.services import reports as svc
from tests.conftest import make_settings
from tests.test_entry_denials import ban, lookup
from tests.test_visitors import new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
OVERVIEW = "/api/v1/reports/overview"
SETTINGS = make_settings()


def kar(y, m, d, hh=0, mm=0) -> datetime:
    """Karachi wall-clock time, as UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=5)


async def counts(admin) -> tuple[int, int]:
    """(denied_entries, watchlist_matches) today, through the API."""
    totals = (await admin.get(OVERVIEW)).json()["totals"]
    return totals["denied_entries"], totals["watchlist_matches"]


async def seed(db, at: datetime, source="check_in", reason="WATCHLIST", **extra) -> dict:
    doc = {"at": at, "reason": reason, "source": source, "source_audit_id": ObjectId()} | extra
    # bypass: only to plant a reason the validator does not allow yet (the counts must keep them apart)
    doc["_id"] = (await db.entry_denials.insert_one(doc, bypass_document_validation=reason != "WATCHLIST")).inserted_id
    return doc


async def range_counts(db, first: date, last: date) -> tuple[int, int]:
    r = svc.report_range(SETTINGS, "custom", first, last)
    c = await svc.security_counts(db, r.start, r.end)
    return c.denied_entries, c.watchlist_matches


# ------------------------------------------------------------------------------------------ sources
async def test_a_refused_check_in_counts_once(admin, guard, harness, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    assert (await check_in(guard, v["id"], directory)).status_code == 403
    assert await counts(admin) == (1, 1)


async def test_a_blocked_lookup_now_counts_as_a_denial_too(admin, guard, harness, directory):  # noqa: F811
    """Before the switch (audit_logs) a lookup refusal counted as a match only: (0, 1). Now (1, 1)."""
    await new_visitor(guard)
    await ban(harness)
    assert (await lookup(guard)).json()["screening"]["status"] == "BLOCKED"
    assert await counts(admin) == (1, 1)


async def test_check_in_and_lookup_refusals_add_up(admin, guard, harness, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    await lookup(guard)
    await check_in(guard, v["id"], directory)
    assert await counts(admin) == (2, 2)


async def test_every_blocked_lookup_is_its_own_attempt(admin, guard, harness, directory):  # noqa: F811
    await new_visitor(guard)
    await ban(harness)
    await lookup(guard)
    await lookup(guard)
    assert await counts(admin) == (2, 2)


async def test_visits_and_other_failures_count_nothing(admin, guard, harness, directory):  # noqa: F811
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()                       # successful check-in
    assert (await check_in(guard, v["id"], directory)).status_code == 409            # already inside
    await guard.post(f"/api/v1/visits/{visit['id']}/check-out")                       # check-out
    assert (await check_in(guard, v["id"], directory, reason_code="OTHER")).status_code == 422     # validation
    assert (await check_in(guard, str(ObjectId()), directory)).status_code == 404     # unknown visitor
    assert (await guard.get("/api/v1/users")).status_code == 403                      # access denied
    await ban(harness, is_active=False)                                               # inactive ban
    assert (await lookup(guard)).json()["screening"]["status"] == "CLEAR"
    await harness.db.watchlist.delete_many({})
    await ban(harness, expires_at=datetime.now(UTC) - timedelta(minutes=1))            # expired ban
    assert (await check_in(guard, v["id"], directory)).status_code == 201
    assert await counts(admin) == (0, 0)


async def test_a_gate_required_refusal_counts_nothing(admin, guard, harness, directory):  # noqa: F811
    await admin.post("/api/v1/gates", json={"name": "East Gate"})
    v = await new_visitor(guard)
    await ban(harness)
    assert (await check_in(guard, v["id"], directory)).json()["error"]["code"] == "gate_required"
    assert await counts(admin) == (0, 0)


# ------------------------------------------------------------------------------------------ no double counting
async def test_audit_entries_are_never_counted(admin, guard, harness, directory):  # noqa: F811
    """A refusal writes two audit entries and one denial: it counts once."""
    v = await new_visitor(guard)
    await ban(harness)
    await check_in(guard, v["id"], directory)
    assert await harness.db.audit_logs.count_documents({"action": {"$in": ["WATCHLIST_MATCH", "VISIT_CHECKED_IN"]}}) \
        == 2
    assert await counts(admin) == (1, 1)
    # Audit entries without a denial document (e.g. not yet backfilled) count nothing on their own.
    now = datetime.now(UTC)
    await harness.db.audit_logs.insert_many([
        {"timestamp": now, "action": "WATCHLIST_MATCH", "result": "SUCCESS", "actor": {}, "resource": {}},
        {"timestamp": now, "action": "VISIT_CHECKED_IN", "result": "DENIED", "actor": {}, "resource": {},
         "metadata": {"reason": "watchlist"}}])
    assert await counts(admin) == (1, 1)


async def test_backfilled_refusals_count_exactly_once(admin, harness):
    now = datetime.now(UTC)
    for minutes in (1, 2):
        await harness.db.audit_logs.insert_one({
            "timestamp": now - timedelta(minutes=minutes), "action": "WATCHLIST_MATCH", "result": "SUCCESS",
            "actor": {"user_id": ObjectId(), "username": "g"}, "resource": {"type": "visitor", "id": ObjectId()},
            "metadata": {"watchlist_id": ObjectId(), "gate_id": ObjectId(), "identifier": "CNIC:***********67-1"}})
        # the old pair: each refused check-in also wrote a denied VISIT_CHECKED_IN
        await harness.db.audit_logs.insert_one({
            "timestamp": now - timedelta(minutes=minutes), "action": "VISIT_CHECKED_IN", "result": "DENIED",
            "actor": {}, "resource": {}, "metadata": {"reason": "watchlist"}})
    assert await counts(admin) == (0, 0)                            # before the backfill: nothing to count
    assert (await denials_svc.backfill_from_audit(harness.db)).created == 2
    assert await counts(admin) == (2, 2)
    await denials_svc.backfill_from_audit(harness.db)               # a second run changes nothing
    assert await counts(admin) == (2, 2)


async def test_runtime_and_backfill_count_once(admin, guard, harness, directory):  # noqa: F811
    v = await new_visitor(guard)
    await ban(harness)
    await check_in(guard, v["id"], directory)
    await lookup(guard)
    assert (await denials_svc.backfill_from_audit(harness.db)).created == 0
    assert await counts(admin) == (2, 2)


async def test_every_source_is_counted(harness):
    for source in ("check_in", "lookup", "audit_backfill"):
        await seed(harness.db, kar(2026, 9, 10, 12), source=source)
    assert await range_counts(harness.db, date(2026, 9, 10), date(2026, 9, 10)) == (3, 3)


async def test_the_two_counts_stay_separate(harness):
    """Only WATCHLIST refusals exist today; another reason would count as a denial, not as a match."""
    await seed(harness.db, kar(2026, 9, 10, 12))
    await seed(harness.db, kar(2026, 9, 10, 13), reason="OTHER")
    assert await range_counts(harness.db, date(2026, 9, 10), date(2026, 9, 10)) == (2, 1)


# ------------------------------------------------------------------------------------------ ranges
async def test_range_edges(harness):
    r = svc.report_range(SETTINGS, "custom", date(2026, 9, 10), date(2026, 9, 11))
    assert (r.start, r.end) == (kar(2026, 9, 10), kar(2026, 9, 12))      # local midnights, in UTC
    await seed(harness.db, r.start)                                     # exactly at the start: in
    await seed(harness.db, r.end - timedelta(milliseconds=1))            # the last moment: in
    await seed(harness.db, r.end)                                       # exactly at the end: out
    await seed(harness.db, r.start - timedelta(milliseconds=1))          # just before: out
    c = await svc.security_counts(harness.db, r.start, r.end)
    assert (c.denied_entries, c.watchlist_matches) == (2, 2)


@pytest.mark.parametrize("preset,now,expected", [
    ("today", kar(2026, 9, 30, 0, 20), 1),         # 00:20 in Karachi (19:20 UTC the day before)
    ("yesterday", kar(2026, 9, 30, 0, 20), 1),
    ("this_week", kar(2026, 9, 30, 12), 2),        # Monday 28 onwards
    ("this_month", kar(2026, 10, 1, 2), 0),
])
async def test_presets_use_karachi_days(harness, preset, now, expected):
    # 23:50 on the 29th and 00:10 on the 30th in Karachi: both the 29th in UTC.
    await seed(harness.db, kar(2026, 9, 29, 23, 50))
    await seed(harness.db, kar(2026, 9, 30, 0, 10))
    await seed(harness.db, kar(2026, 9, 27, 12))    # Sunday: last week
    r = svc.report_range(SETTINGS, preset, None, None, now=now)
    c = await svc.security_counts(harness.db, r.start, r.end)
    assert (c.denied_entries, c.watchlist_matches) == (expected, expected)


async def test_the_overview_reports_the_new_counts_for_any_range(harness):
    await seed(harness.db, kar(2026, 9, 2, 9))
    await seed(harness.db, kar(2026, 9, 5, 9), source="lookup")
    await seed(harness.db, kar(2026, 8, 31, 23, 59))                   # outside
    out = await svc.overview(harness.db, svc.report_range(SETTINGS, "custom", date(2026, 9, 1), date(2026, 9, 7)),
                             now=kar(2026, 9, 30))
    assert (out["totals"]["denied_entries"], out["totals"]["watchlist_matches"]) == (2, 2)
    assert out["totals"]["visits"] == 0                                 # the rest of the overview is unchanged


# ------------------------------------------------------------------------------------------ index
def _stages(plan) -> list[dict]:
    found, stack = [], [plan]
    while stack:
        p = stack.pop()
        if isinstance(p, dict):
            if "stage" in p:
                found.append(p)
            stack.extend(p.values())
        elif isinstance(p, list):
            stack.extend(p)
    return found


async def test_the_counts_use_the_at_index(harness):
    for i in range(200):
        await seed(harness.db, kar(2026, 9, 1) + timedelta(hours=i))
    window = {"at": {"$gte": kar(2026, 9, 3), "$lt": kar(2026, 9, 4)}}
    plans = {}
    for name, query in (("denied", window), ("matches", window | {"reason": "WATCHLIST"})):
        e = await harness.db.command("explain", {"count": "entry_denials", "query": query}, verbosity="executionStats")
        plans[name] = e
        stages = _stages(e["queryPlanner"]["winningPlan"])
        assert {s.get("indexName") for s in stages if s.get("indexName")} == {"newest_first"}, name
        assert not any(s["stage"] == "COLLSCAN" for s in stages), name
        assert e["executionStats"]["totalKeysExamined"] <= 25, name        # one day of the 200 hours
    # All refusals: answered from the index alone; WATCHLIST ones: the index, then the day's documents.
    assert plans["denied"]["executionStats"]["totalDocsExamined"] == 0
    assert plans["matches"]["executionStats"]["totalDocsExamined"] == 24
