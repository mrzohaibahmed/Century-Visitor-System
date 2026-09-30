"""Reports step 2: GET /reports/overview and GET /reports/visits (administrators only).

Aggregations are checked on a controlled dataset with fixed times (never the machine clock); the HTTP
tests check access, validation, masking and paging."""
import itertools
from datetime import UTC, date, datetime, timedelta

import pytest
from bson import ObjectId

from app.core.pagination import encode_sort_cursor
from app.schemas.reports import VisitReportSort
from app.services import reports as svc
from app.services.visits import VisitFilter
from tests.conftest import make_settings
from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
OVERVIEW = "/api/v1/reports/overview"
VISITS = "/api/v1/reports/visits"
SETTINGS = make_settings()                 # Asia/Karachi (UTC+5, no daylight saving)
_numbers = itertools.count(1)


def kar(y, m, d, hh=0, mm=0) -> datetime:
    """Karachi wall-clock time, as UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=5)


def custom(first: date, last: date):
    return svc.report_range(SETTINGS, "custom", first, last)


async def seed(db, at: datetime, *, minutes: int | None = None, visitor=None, dep=None, dep_name="HR", gate=None,
               by=None, out_by=None, reason="OFFICIAL_MEETING", host=None) -> dict:
    """One visit checked in at `at`; checked out after `minutes` (None: still inside)."""
    by = by or ObjectId()
    doc = {
        "visit_number": f"V-2026-{next(_numbers):06d}", "visitor_id": visitor or ObjectId(),
        "host_id": host, "host_unlisted": host is None, "department_id": dep or ObjectId(), "gate_id": gate,
        "status": "CHECKED_IN" if minutes is None else "CHECKED_OUT", "check_in_at": at,
        "check_out_at": None if minutes is None else at + timedelta(minutes=minutes),
        "checked_in_by": by, "checked_out_by": None if minutes is None else (out_by or by),
        "reason_code": reason, "reason_note": None, "belongings": ["Laptop"], "photo_id": None, "pass": None,
        "snapshot": {"visitor_name": "Test Visitor", "department_name": dep_name, "host_name": "Sara Ahmed",
                     "gate_name": "Main Gate", "checked_in_by_name": "Guard"},
        "created_at": at, "updated_at": at,
    }
    doc["_id"] = (await db.visits.insert_one(doc)).inserted_id
    return doc


# ------------------------------------------------------------------------------------------ access
async def test_admins_can_open_both_reports(admin):
    for path in (OVERVIEW, VISITS):
        r = await admin.get(path)
        assert r.status_code == 200, r.text
        assert r.json()["range"]["preset"] == "today" and r.json()["range"]["timezone"] == "Asia/Karachi"


async def test_guards_are_refused_and_the_attempt_is_audited(harness, guard):
    for path in (OVERVIEW, VISITS):
        r = await guard.get(path)
        assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
        assert "items" not in r.text and "totals" not in r.text
    denied = await harness.db.audit_logs.find({"action": "ACCESS_DENIED"}).to_list(length=10)
    assert {(d["metadata"]["path"], d["metadata"]["permission"]) for d in denied} == {
        (OVERVIEW, "reports:view"), (VISITS, "reports:view")}


async def test_no_filter_or_parameter_gets_a_guard_in(harness, guard):
    me = await harness.db.users.find_one({"username": "guard1"})
    attempts = [
        {"guard_id": str(me["_id"])},                                       # "only my own visits"
        {"range": "custom", "from": "2026-01-01", "to": "2026-01-31"},
        {"range": "nonsense", "limit": 999, "host_id": "not-an-id"},        # invalid: still 403, not 422
        {"cursor": encode_sort_cursor("check_in_desc", datetime.now(UTC), ObjectId())},
        {"role": "ADMIN", "user_id": str(me["_id"])},                       # ignored: identity is the session
    ]
    for params in attempts:
        for path in (OVERVIEW, VISITS):
            assert (await guard.get(path, params=params)).status_code == 403, (path, params)


async def test_anonymous_requests_are_refused(harness):
    c = harness.client()
    for path in (OVERVIEW, VISITS):
        assert (await c.get(path)).status_code == 401


@pytest.mark.parametrize("params,status,code", [
    ({"range": "custom", "from": "2026-09-02", "to": "2026-09-01"}, 422, "invalid_range"),
    ({"range": "custom", "from": "2025-01-01", "to": "2026-01-02"}, 422, "invalid_range"),     # 367 days
    ({"range": "custom", "from": "2026-09-01"}, 422, "invalid_range"),
    ({"range": "today", "from": "2026-09-01", "to": "2026-09-01"}, 422, "invalid_range"),
    ({"range": "last_year"}, 422, "validation_error"),
    ({"from": "31-12-2026", "range": "custom", "to": "2026-12-31"}, 422, "validation_error"),
])
async def test_invalid_ranges(admin, params, status, code):
    for path in (OVERVIEW, VISITS):
        r = await admin.get(path, params=params)
        assert (r.status_code, r.json()["error"]["code"]) == (status, code), (path, params, r.text)


@pytest.mark.parametrize("params,status,code", [
    ({"host_id": "not-an-id"}, 422, "validation_error"),
    ({"guard_id": "0" * 23}, 422, "validation_error"),
    ({"status": "CANCELLED"}, 422, "validation_error"),
    ({"reason_code": "SHOPPING"}, 422, "validation_error"),
    ({"sort": "name_asc"}, 422, "validation_error"),
    ({"limit": 101}, 422, "validation_error"),
    ({"limit": 0}, 422, "validation_error"),
    ({"q": "x" * 101}, 422, "validation_error"),
    ({"cursor": "garbage"}, 400, "invalid_cursor"),
    ({"cursor": encode_sort_cursor("check_in_asc", datetime.now(UTC), ObjectId())}, 400, "invalid_cursor"),
    ({"q": {"$gt": ""}}, 200, None),                     # an operator is just text here, never a query
])
async def test_invalid_visit_report_parameters(admin, params, status, code):
    r = await admin.get(VISITS, params=params)
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code


# ------------------------------------------------------------------------------------------ overview
async def test_overview_totals_and_series(harness):
    db = harness.db
    hr, stores = ObjectId(), ObjectId()
    a, b, c = ObjectId(), ObjectId(), ObjectId()
    await seed(db, kar(2026, 9, 1, 10, 15), minutes=60, visitor=a, dep=hr)
    await seed(db, kar(2026, 9, 1, 10, 45), minutes=120, visitor=b, dep=hr)
    await seed(db, kar(2026, 9, 2, 0, 30), minutes=30, visitor=a, dep=stores, dep_name="Stores")   # after midnight
    await seed(db, kar(2026, 9, 3, 9, 0), visitor=c, dep=stores, dep_name="Stores")               # still inside
    # Outside the range: not counted, except that the one still inside is inside NOW.
    await seed(db, kar(2026, 8, 31, 23, 59), visitor=ObjectId())
    await seed(db, kar(2026, 9, 4, 0, 0), minutes=10)

    now = kar(2026, 9, 30, 12)
    out = await svc.overview(db, custom(date(2026, 9, 1), date(2026, 9, 3)), now=now)
    assert out["totals"] == {"visits": 4, "unique_visitors": 3, "inside_now": 2, "checked_out": 3,
                             "denied_entries": 0, "watchlist_matches": 0, "avg_duration_minutes": 70}
    s = out["series"]
    assert s["bucket"] == "day"
    assert [(p["start"].isoformat(), p["count"]) for p in s["over_time"]] == [
        ("2026-09-01T00:00:00+05:00", 2), ("2026-09-02T00:00:00+05:00", 1), ("2026-09-03T00:00:00+05:00", 1)]
    assert [(d["id"], d["name"], d["count"]) for d in s["by_department"]] == [
        (str(hr), "HR", 2), (str(stores), "Stores", 2)]
    assert s["by_status"] == [{"status": "CHECKED_IN", "count": 1}, {"status": "CHECKED_OUT", "count": 3}]
    hours = {h["hour"]: h["count"] for h in s["peak_hours"] if h["count"]}
    assert hours == {10: 2, 0: 1, 9: 1} and len(s["peak_hours"]) == 24         # local hours, all 24 listed


async def test_visits_still_inside_never_change_the_average(harness):
    db = harness.db
    await seed(db, kar(2026, 9, 1, 9), minutes=40)
    await seed(db, kar(2026, 9, 1, 9), minutes=20)
    r = custom(date(2026, 9, 1), date(2026, 9, 1))
    before = await svc.overview(db, r, now=kar(2026, 9, 1, 12))
    await seed(db, kar(2026, 9, 1, 1))                               # inside for 11 hours at "now"
    after = await svc.overview(db, r, now=kar(2026, 9, 1, 12))
    assert before["totals"]["avg_duration_minutes"] == after["totals"]["avg_duration_minutes"] == 30
    only_inside = custom(date(2026, 9, 2), date(2026, 9, 2))
    await seed(db, kar(2026, 9, 2, 8))
    assert (await svc.overview(db, only_inside, now=kar(2026, 9, 2, 20)))["totals"]["avg_duration_minutes"] is None


async def test_inside_now_is_the_current_state_whatever_the_range(harness):
    db = harness.db
    await seed(db, kar(2026, 9, 20, 9))                               # inside since the 20th
    await seed(db, kar(2026, 9, 5, 9))                                # inside since the 5th (a long stay)
    await seed(db, kar(2026, 9, 5, 10), minutes=15)
    for first, last in ((date(2026, 9, 1), date(2026, 9, 15)), (date(2025, 1, 1), date(2025, 1, 2))):
        out = await svc.overview(db, custom(first, last), now=kar(2026, 9, 30))
        assert out["totals"]["inside_now"] == 2, (first, last)
    early = await svc.overview(db, custom(date(2026, 9, 1), date(2026, 9, 15)), now=kar(2026, 9, 30))
    assert early["totals"]["visits"] == 2                              # the range still scopes the rest


async def test_one_day_uses_hourly_buckets(harness):
    db = harness.db
    await seed(db, kar(2026, 9, 30, 0, 5), minutes=5)                  # 00:05 local = 19:05 UTC the day before
    await seed(db, kar(2026, 9, 30, 14, 59), minutes=5)
    await seed(db, kar(2026, 9, 30, 14, 0), minutes=5)
    await seed(db, kar(2026, 10, 1, 0, 0), minutes=5)                  # next day: not counted
    now = kar(2026, 9, 30, 18)
    out = await svc.overview(db, svc.report_range(SETTINGS, "today", None, None, now=now), now=now)
    series = out["series"]["over_time"]
    assert out["series"]["bucket"] == "hour" and len(series) == 24
    assert series[0]["start"].isoformat() == "2026-09-30T00:00:00+05:00"
    assert series[23]["start"].isoformat() == "2026-09-30T23:00:00+05:00"
    assert {p["start"].hour: p["count"] for p in series if p["count"]} == {0: 1, 14: 2}


@pytest.mark.parametrize("preset,now,expected", [
    # Visits at 23:30 on Sun 27, 08:00 on Mon 28 and 00:10 on Wed 30 September; 01:00 on Thu 1 October.
    ("today", kar(2026, 9, 30, 0, 20), 1),                  # just after midnight in Karachi (19:20 UTC the 29th)
    ("yesterday", kar(2026, 9, 29, 12), 1),                 # Mon 28
    ("this_week", kar(2026, 9, 30, 12), 2),                 # Monday 28 onwards: not Sunday 27
    ("this_month", kar(2026, 10, 1, 2), 1),                 # the new month only
    ("this_month", kar(2026, 9, 30, 23), 3),
])
async def test_presets_count_the_right_local_days(harness, preset, now, expected):
    db = harness.db
    for at in (kar(2026, 9, 27, 23, 30), kar(2026, 9, 28, 8), kar(2026, 9, 30, 0, 10), kar(2026, 10, 1, 1)):
        await seed(db, at, minutes=10)
    r = svc.report_range(SETTINGS, preset, None, None, now=now)
    assert (await svc.overview(db, r, now=now))["totals"]["visits"] == expected


async def test_custom_ranges_convert_local_days_to_utc(harness):
    db = harness.db
    await seed(db, datetime(2026, 9, 24, 19, 0, tzinfo=UTC), minutes=1)     # 25 Sept 00:00 in Karachi
    await seed(db, datetime(2026, 9, 24, 18, 59, tzinfo=UTC), minutes=1)    # 24 Sept 23:59 in Karachi
    out = await svc.overview(db, custom(date(2026, 9, 25), date(2026, 9, 25)), now=kar(2026, 9, 30))
    assert out["totals"]["visits"] == 1


async def test_renamed_departments_show_their_current_name(harness, admin):
    dep = (await admin.post("/api/v1/departments", json={"name": "HR"})).json()
    await seed(harness.db, kar(2026, 9, 1, 9), minutes=5, dep=ObjectId(dep["id"]), dep_name="HR")
    await admin.patch(f"/api/v1/departments/{dep['id']}", json={"name": "People"})
    out = await svc.overview(harness.db, custom(date(2026, 9, 1), date(2026, 9, 1)), now=kar(2026, 9, 2))
    assert out["series"]["by_department"] == [{"id": dep["id"], "name": "People", "count": 1}]


async def test_an_empty_range(harness):
    out = await svc.overview(harness.db, custom(date(2026, 9, 1), date(2026, 9, 7)), now=kar(2026, 9, 30))
    assert out["totals"] == {"visits": 0, "unique_visitors": 0, "inside_now": 0, "checked_out": 0,
                             "denied_entries": 0, "watchlist_matches": 0, "avg_duration_minutes": None}
    assert len(out["series"]["over_time"]) == 7 and all(p["count"] == 0 for p in out["series"]["over_time"])
    assert out["series"]["by_department"] == []


async def test_the_overview_over_http(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    visit = (await check_in(guard, v["id"], directory)).json()
    await guard.post(f"/api/v1/visits/{visit['id']}/check-out")
    body = (await admin.get(OVERVIEW)).json()                        # today, by the real clock
    assert body["totals"]["visits"] == 1 and body["totals"]["checked_out"] == 1
    assert body["series"]["bucket"] == "hour" and len(body["series"]["over_time"]) == 24
    assert body["series"]["over_time"][0]["start"].endswith("+05:00")
    assert body["series"]["by_department"][0]["name"] == "HR"


# ------------------------------------------------------------------------------------------ security counts
async def _ban(harness):
    await harness.db.watchlist.insert_one({
        "identifier": f"CNIC:{CNIC}", "identity": {"type": "CNIC", "number": CNIC}, "reason": "Theft of property.",
        "is_active": True, "expires_at": None, "created_by": ObjectId(), "created_at": datetime.now(UTC)})


async def test_one_refused_entry_counts_once_in_each(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await _ban(harness)
    assert (await check_in(guard, v["id"], directory)).status_code == 403
    # The sequence behind one refusal: exactly one WATCHLIST_MATCH and one denied VISIT_CHECKED_IN.
    assert await harness.db.audit_logs.count_documents({"action": {"$in": ["WATCHLIST_MATCH", "VISIT_CHECKED_IN"]}}) \
        == 2
    now = datetime.now(UTC)
    counts = await svc.security_counts(harness.db, now - timedelta(hours=1), now + timedelta(minutes=1))
    assert (counts.denied_entries, counts.watchlist_matches) == (1, 1)
    totals = (await admin.get(OVERVIEW)).json()["totals"]
    assert (totals["denied_entries"], totals["watchlist_matches"], totals["visits"]) == (1, 1, 0)

    # A second refused attempt: two of each.
    assert (await check_in(guard, v["id"], directory)).status_code == 403
    totals = (await admin.get(OVERVIEW)).json()["totals"]
    assert (totals["denied_entries"], totals["watchlist_matches"]) == (2, 2)


async def test_other_refusals_and_events_are_not_counted(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await check_in(guard, v["id"], directory)
    assert (await check_in(guard, v["id"], directory)).status_code == 409      # already inside: not a denial
    await guard.get(OVERVIEW)                                                    # ACCESS_DENIED: not a denial
    now = datetime.now(UTC)
    # A denied check-in for another reason, if one is ever added, is not a watchlist denial.
    await harness.db.audit_logs.insert_one({"timestamp": now, "action": "VISIT_CHECKED_IN", "result": "DENIED",
                                            "actor": {}, "resource": {}, "metadata": {"reason": "other"}})
    counts = await svc.security_counts(harness.db, now - timedelta(hours=1), now + timedelta(minutes=1))
    assert (counts.denied_entries, counts.watchlist_matches) == (0, 0)


async def test_security_counts_follow_the_range(harness):
    # Since step 4 the counts come from entry_denials (see test_security_counts.py).
    inside, before = kar(2026, 9, 2, 0, 30), kar(2026, 9, 1, 23, 50)
    for at in (inside, before):
        await harness.db.entry_denials.insert_one({"at": at, "reason": "WATCHLIST", "source": "check_in",
                                                   "source_audit_id": ObjectId()})
    out = await svc.overview(harness.db, custom(date(2026, 9, 2), date(2026, 9, 2)), now=kar(2026, 9, 3))
    assert (out["totals"]["denied_entries"], out["totals"]["watchlist_matches"]) == (1, 1)


# ------------------------------------------------------------------------------------------ visit report
@pytest.fixture
async def people(harness, admin, guard, directory):  # noqa: F811
    """Two real visits by the API (one checked out) plus the users involved."""
    a = await new_visitor(guard)
    b = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2", phone="0321-7654321")
    va = (await check_in(guard, a["id"], directory)).json()
    vb = (await check_in(guard, b["id"], directory, host_id=None, unlisted_host_name="Imran Ali",
                         department_id=directory["other_dep"]["id"], reason_code="DELIVERY")).json()
    await admin.post(f"/api/v1/visits/{va['id']}/check-out")                 # checked out by the admin
    users = {u["username"]: u["_id"] async for u in harness.db.users.find()}
    return {"a": a, "b": b, "va": va, "vb": vb, "users": users, **directory}


async def test_the_visit_report_filters(admin, people):
    va, vb = people["va"]["visit_number"], people["vb"]["visit_number"]

    async def numbers(**params):
        r = await admin.get(VISITS, params=params)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == len(body["items"])                    # everything fits on one page here
        return [i["visit_number"] for i in body["items"]]

    assert await numbers() == [vb, va]
    assert await numbers(status="CHECKED_OUT") == [va]
    assert await numbers(status="CHECKED_IN") == [vb]
    assert await numbers(host_id=people["host"]["id"]) == [va]
    assert await numbers(department_id=people["other_dep"]["id"]) == [vb]
    assert await numbers(gate_id=people["gate"]["id"]) == [vb, va]
    assert await numbers(gate_id="0" * 24) == []
    assert await numbers(reason_code="DELIVERY") == [vb]
    assert await numbers(guard_id=str(people["users"]["guard1"])) == [vb, va]     # checked both in
    assert await numbers(guard_id=str(people["users"]["admin"])) == [va]          # checked one out
    assert await numbers(q="alia") == [vb]
    assert await numbers(q="3520112345671") == [va]                               # CNIC, any format
    assert await numbers(q="0321 7654321") == [vb]                                # phone
    assert await numbers(q=va.lower()) == [va]                                    # visit number
    assert await numbers(q="nobody") == []
    assert await numbers(range="yesterday") == []
    assert await numbers(status="CHECKED_OUT", gate_id=people["gate"]["id"], q="ali khan") == [va]


async def test_rows_are_masked_and_carry_nothing_private(admin, people):
    body = (await admin.get(VISITS)).json()
    text = str(body)
    row = next(i for i in body["items"] if i["visit_number"] == people["va"]["visit_number"])
    assert row["id_type"] == "CNIC" and row["id_number"] == "***********67-1" and row["phone"] == "*******4567"
    for secret in (CNIC, CNIC.replace("-", ""), "03001234567", "35201-7654321-2", "03217654321"):
        assert secret not in text
    assert set(row) == {"id", "visit_number", "visitor", "id_type", "id_number", "phone", "host", "host_unlisted",
                        "department", "reason_code", "reason_note", "gate", "check_in_at", "check_out_at",
                        "duration_minutes", "status", "checked_in_by", "checked_out_by"}
    assert row["checked_in_by"]["name"] == "Guard1" and row["checked_out_by"]["name"] == "Admin"
    other = next(i for i in body["items"] if i["visit_number"] == people["vb"]["visit_number"])
    assert other["host_unlisted"] is True and other["host"] == {"id": None, "name": "Imran Ali"}


async def test_a_too_broad_name_search_is_refused(admin, people, monkeypatch):
    monkeypatch.setattr(svc, "REPORT_VISITOR_MATCHES", 1)
    r = await admin.get(VISITS, params={"q": "a"})                       # Ali Khan and Alia Noor
    assert r.status_code == 422 and r.json()["error"]["code"] == "search_too_broad"
    assert (await admin.get(VISITS, params={"q": "alia"})).status_code == 200


async def test_the_existing_visit_history_is_unchanged(guard, people):
    r = await guard.get("/api/v1/visits")
    assert r.status_code == 200 and "id_number" not in r.text and "total" not in r.json()
    assert set(r.json()) == {"items", "next_cursor"}


# ------------------------------------------------------------------------------------------ sorting and paging
async def _sorted_dataset(db):
    """Five visits on 1 September: fixed times and durations, two still inside, one tie on check-in."""
    rows = {
        "a": await seed(db, kar(2026, 9, 1, 8), minutes=30),
        "b": await seed(db, kar(2026, 9, 1, 9), minutes=240),
        "c": await seed(db, kar(2026, 9, 1, 9), minutes=90),              # same check-in time as b
        "d": await seed(db, kar(2026, 9, 1, 10)),                         # inside
        "e": await seed(db, kar(2026, 9, 1, 11)),                         # inside
    }
    return {k: v["visit_number"] for k, v in rows.items()}, {v["visit_number"]: k for k, v in rows.items()}


async def _walk(db, sort, now, limit):
    f = VisitFilter(start=kar(2026, 9, 1), end=kar(2026, 9, 2))
    seen, cursor, pages = [], None, 0
    while True:
        docs, cursor, total, _ = await svc.visit_report(db, f, sort=sort, cursor=cursor, limit=limit, now=now)
        seen += [d["visit_number"] for d in docs]
        pages += 1
        assert total == 5
        if not cursor:
            return seen, pages


@pytest.mark.parametrize("limit", [1, 2, 100])
async def test_every_sort_pages_without_repeats_or_gaps(harness, limit):
    number, name = await _sorted_dataset(harness.db)
    now = kar(2026, 9, 1, 12)          # d inside 120 min, e inside 60 min
    expected = {
        VisitReportSort.CHECK_IN_DESC: ["e", "d", "c", "b", "a"],        # the tie b/c: newest _id first
        VisitReportSort.CHECK_IN_ASC: ["a", "b", "c", "d", "e"],
        VisitReportSort.CHECK_OUT_DESC: ["b", "c", "a", "e", "d"],       # b 13:00, c 10:30, a 08:30; then inside
        VisitReportSort.DURATION_DESC: ["b", "d", "c", "e", "a"],        # 240, 120 (inside), 90, 60 (inside), 30
    }
    for sort, order in expected.items():
        seen, pages = await _walk(harness.db, sort, now, limit)
        assert [name[n] for n in seen] == order, sort
        assert pages == -(-5 // limit), sort


async def test_duration_paging_keeps_the_first_pages_moment(harness):
    """Visits inside keep growing; later pages must use the moment of the first page."""
    await _sorted_dataset(harness.db)
    f = VisitFilter(start=kar(2026, 9, 1), end=kar(2026, 9, 2))
    first, cursor, _, as_of = await svc.visit_report(harness.db, f, sort=VisitReportSort.DURATION_DESC, cursor=None,
                                                     limit=2, now=kar(2026, 9, 1, 12))
    # Hours later, e (inside) would now outlast c; the pinned moment keeps the original order.
    rest, _, _, as_of2 = await svc.visit_report(harness.db, f, sort=VisitReportSort.DURATION_DESC, cursor=cursor,
                                                limit=10, now=kar(2026, 9, 1, 23))
    assert as_of == as_of2 == kar(2026, 9, 1, 12)
    assert len({d["_id"] for d in first + rest}) == 5


async def test_the_total_follows_the_filters_not_the_page(harness):
    gate = ObjectId()
    for i in range(7):
        await seed(harness.db, kar(2026, 9, 1, 8, i), minutes=5, gate=gate if i % 2 else None)
    f = VisitFilter(start=kar(2026, 9, 1), end=kar(2026, 9, 2), gate_id=gate)
    docs, cursor, total, _ = await svc.visit_report(harness.db, f, sort=VisitReportSort.CHECK_IN_DESC, cursor=None,
                                                    limit=2)
    assert (len(docs), total, bool(cursor)) == (2, 3, True)


async def test_reports_are_always_bounded_by_a_range(harness):
    with pytest.raises(ValueError):
        await svc.visit_report(harness.db, VisitFilter(), sort=VisitReportSort.CHECK_IN_DESC, cursor=None, limit=5)


async def test_pages_over_http(admin, harness):
    for i in range(3):
        await seed(harness.db, datetime.now(UTC) - timedelta(minutes=i), minutes=None if i else 1)
    seen, cursor = [], None
    while True:
        params = {"limit": 1, "sort": "duration_desc"} | ({"cursor": cursor} if cursor else {})
        body = (await admin.get(VISITS, params=params)).json()
        assert body["total"] == 3
        seen += [i["visit_number"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(set(seen)) == 3


# ------------------------------------------------------------------------------------------ indexes
def _index_names(plan) -> set[str]:
    found: set[str] = set()
    stack = [plan]
    while stack:
        p = stack.pop()
        if isinstance(p, dict):
            if p.get("indexName"):
                found.add(p["indexName"])
            stack.extend(p.values())
        elif isinstance(p, list):
            stack.extend(p)
    return found


async def test_the_guard_and_gate_filters_use_their_indexes(harness):
    db = harness.db
    guards, gates = [ObjectId() for _ in range(10)], [ObjectId() for _ in range(10)]
    docs = []
    for i in range(600):
        at = kar(2026, 9, 1) + timedelta(minutes=7 * i)
        docs.append({"visit_number": f"V-2026-9{i:05d}", "visitor_id": ObjectId(), "status": "CHECKED_OUT",
                     "check_in_at": at, "check_out_at": at + timedelta(minutes=5), "checked_in_by": guards[i % 10],
                     "checked_out_by": guards[(i + 3) % 10], "gate_id": gates[i % 10], "reason_code": "OTHER",
                     "snapshot": {"visitor_name": "X"}, "created_at": at, "updated_at": at})
    await db.visits.insert_many(docs)
    r = custom(date(2026, 9, 1), date(2026, 9, 3))
    for f, expected in (
        (VisitFilter(start=r.start, end=r.end, guard_id=guards[0]),
         {"checked_in_by_history", "checked_out_by_history"}),
        (VisitFilter(start=r.start, end=r.end, gate_id=gates[0]), {"gate_history"}),
    ):
        query = await svc.report_visit_query(db, f)
        page = await db.visits.find(query).sort([("check_in_at", -1), ("_id", -1)]).limit(26).explain()
        count = await db.command("explain", {"count": "visits", "query": query}, verbosity="queryPlanner")
        assert _index_names(page["queryPlanner"]["winningPlan"]) == expected
        assert _index_names(count["queryPlanner"]["winningPlan"]) == expected
