"""Reports step 5: visitor summary, hosts, departments, guards, currently inside and denials.

Aggregations are checked on controlled data with fixed times; HTTP tests check access, masking and paging."""
import itertools
from datetime import UTC, date, datetime, timedelta

import pytest
from bson import ObjectId

from app.services import entry_denials as denials_svc
from app.services import reports as svc
from app.services.visits import VisitFilter
from tests.conftest import make_settings
from tests.test_entry_denials import ban, lookup
from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
SETTINGS = make_settings()
ENDPOINTS = ["/api/v1/reports/visitors", "/api/v1/reports/hosts", "/api/v1/reports/departments",
             "/api/v1/reports/guards", "/api/v1/reports/inside", "/api/v1/reports/denials"]
_numbers = itertools.count(1)


def kar(y, m, d, hh=0, mm=0) -> datetime:
    """Karachi wall-clock time, as UTC."""
    return datetime(y, m, d, hh, mm, tzinfo=UTC) - timedelta(hours=5)


def custom(first: date, last: date):
    return svc.report_range(SETTINGS, "custom", first, last)


SEPT = custom(date(2026, 9, 1), date(2026, 9, 30))


async def visit(db, at, *, minutes=None, visitor=None, visitor_name="Test Visitor", host=None, host_name="Sara Ahmed",
                dep=None, dep_name="HR", gate=None, by=None, out_by=None, out_at=None) -> dict:
    """One visit checked in at `at`; checked out after `minutes` (or at `out_at`); None: still inside."""
    by = by or ObjectId()
    if out_at is None and minutes is not None:
        out_at = at + timedelta(minutes=minutes)
    doc = {
        "visit_number": f"V-2026-{next(_numbers) + 500000:06d}", "visitor_id": visitor or ObjectId(),
        "host_id": host, "host_unlisted": host is None, "department_id": dep, "gate_id": gate,
        "status": "CHECKED_OUT" if out_at else "CHECKED_IN", "check_in_at": at, "check_out_at": out_at,
        "checked_in_by": by, "checked_out_by": (out_by or by) if out_at else None, "reason_code": "OFFICIAL_MEETING",
        "belongings": ["Laptop"], "pass": None, "photo_id": None,
        "snapshot": {"visitor_name": visitor_name, "host_name": host_name, "department_name": dep_name,
                     "gate_name": "Main Gate", "checked_in_by_name": "Guard"},
        "created_at": at, "updated_at": at,
    }
    doc["_id"] = (await db.visits.insert_one(doc)).inserted_id
    return doc


async def denial(db, at, *, source="check_in", reason="WATCHLIST", **fields) -> dict:
    doc = {"at": at, "reason": reason, "source": source, "source_audit_id": ObjectId()} | fields
    doc["_id"] = (await db.entry_denials.insert_one(doc, bypass_document_validation=reason != "WATCHLIST")).inserted_id
    return doc


def _plan_indexes(plan) -> set[str]:
    found, stack = set(), [plan]
    while stack:
        p = stack.pop()
        if isinstance(p, dict):
            if p.get("indexName"):
                found.add(p["indexName"])
            if p.get("stage") == "COLLSCAN":
                found.add("COLLSCAN")
            stack.extend(p.values())
        elif isinstance(p, list):
            stack.extend(p)
    return found


# ------------------------------------------------------------------------------------------ access
@pytest.mark.parametrize("path", ENDPOINTS)
async def test_access(harness, admin, guard, path):
    assert (await harness.client().get(path)).status_code == 401
    r = await guard.get(path)
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    audit = await harness.db.audit_logs.find_one({"action": "ACCESS_DENIED", "metadata.path": path})
    assert audit["metadata"]["permission"] == "reports:view"
    assert (await admin.get(path)).status_code == 200


@pytest.mark.parametrize("path", ENDPOINTS)
async def test_no_parameter_lets_a_guard_in(harness, guard, path):
    me = await harness.db.users.find_one({"username": "guard1"})
    for params in ({"guard_id": str(me["_id"])}, {"range": "custom", "from": "2026-09-01", "to": "2026-09-30"},
                   {"role": "ADMIN", "user_id": str(me["_id"])}, {"limit": "not-a-number"}):
        assert (await guard.get(path, params=params)).status_code == 403, params


@pytest.mark.parametrize("path,params,code", [
    ("/api/v1/reports/visitors", {"sort": "name"}, "validation_error"),
    ("/api/v1/reports/visitors", {"cursor": "garbage"}, "invalid_cursor"),
    ("/api/v1/reports/hosts", {"department_id": "nope"}, "validation_error"),
    ("/api/v1/reports/hosts", {"limit": 501}, "validation_error"),
    ("/api/v1/reports/departments", {"range": "custom", "from": "2026-09-02", "to": "2026-09-01"}, "invalid_range"),
    ("/api/v1/reports/guards", {"range": "decade"}, "validation_error"),
    ("/api/v1/reports/inside", {"sort": "duration_desc"}, "validation_error"),
    ("/api/v1/reports/denials", {"source": "guess"}, "validation_error"),
    ("/api/v1/reports/denials", {"guard_id": "0" * 23}, "validation_error"),
])
async def test_invalid_parameters(admin, path, params, code):
    r = await admin.get(path, params=params)
    assert r.status_code in (400, 422) and r.json()["error"]["code"] == code, r.text


# ------------------------------------------------------------------------------------------ visitor summary
async def test_visitor_summary_groups_the_range(harness):
    db = harness.db
    a, b, c = ObjectId(), ObjectId(), ObjectId()
    await visit(db, kar(2026, 9, 2, 9), minutes=30, visitor=a, visitor_name="Ali Khan")
    await visit(db, kar(2026, 9, 5, 9), minutes=90, visitor=a, visitor_name="Ali Khan")
    await visit(db, kar(2026, 9, 29, 9), visitor=a, visitor_name="Ali Khan")               # inside now
    await visit(db, kar(2026, 8, 20, 9), minutes=5, visitor=a, visitor_name="Ali Khan")    # before the range
    await visit(db, kar(2026, 9, 10, 9), minutes=45, visitor=b, visitor_name="Alia Noor")
    await visit(db, kar(2026, 8, 1, 9), visitor=c, visitor_name="Old Visitor")             # inside, not in range
    f = VisitFilter(start=SEPT.start, end=SEPT.end)
    groups, cursor, total, _, inside = await svc.visitor_summary(db, f, sort="last_visit_desc", cursor=None, limit=25)
    assert total == 2 and cursor is None and [g["_id"] for g in groups] == [a, b]
    ga = groups[0]
    assert (ga["visits"], ga["completed"], round(ga["avg_ms"] / 60000)) == (3, 2, 60)     # the visit inside: left out
    assert (ga["first"], ga["last"]) == (kar(2026, 9, 2, 9), kar(2026, 9, 29, 9))
    assert inside == {a}                                                                 # current state
    groups, *_ = await svc.visitor_summary(db, f, sort="visits_desc", cursor=None, limit=25)
    assert [g["visits"] for g in groups] == [3, 1]


async def test_visitor_summary_pages_without_repeats(harness):
    db = harness.db
    ids = []
    for i in range(5):
        v = ObjectId()
        ids.append(v)
        for _ in range(i % 3 + 1):              # ties on the visit count
            await visit(db, kar(2026, 9, 1 + i, 9), minutes=5, visitor=v)
    f = VisitFilter(start=SEPT.start, end=SEPT.end)
    for sort in ("last_visit_desc", "visits_desc"):
        seen, cursor = [], None
        while True:
            groups, cursor, total, *_ = await svc.visitor_summary(db, f, sort=sort, cursor=cursor, limit=2)
            seen += [g["_id"] for g in groups]
            assert total == 5
            if not cursor:
                break
        assert sorted(seen) == sorted(ids) and len(seen) == 5, sort


async def test_visitor_summary_over_http_is_masked(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    first = (await check_in(guard, v["id"], directory)).json()
    await guard.post(f"/api/v1/visits/{first['id']}/check-out")
    await check_in(guard, v["id"], directory)
    body = (await admin.get("/api/v1/reports/visitors")).json()
    [row] = body["items"]
    assert set(row) == {"visitor", "id_type", "id_number", "phone", "visits", "completed_visits", "first_visit_at",
                        "last_visit_at", "avg_duration_minutes", "inside_now"}
    assert (row["visitor"]["name"], row["visits"], row["completed_visits"], row["inside_now"]) == \
        ("Ali Khan", 2, 1, True)
    assert row["id_number"] == "***********67-1" and row["phone"] == "*******4567"
    for secret in (CNIC, CNIC.replace("-", ""), "03001234567", "Laptop", "photo", "pass"):
        assert secret not in str(body), secret
    assert (await admin.get("/api/v1/reports/visitors", params={"q": "nobody"})).json()["total"] == 0
    assert (await admin.get("/api/v1/reports/visitors", params={"range": "yesterday"})).json()["items"] == []


# ------------------------------------------------------------------------------------------ hosts, departments
async def test_hosts_and_departments(harness, admin):
    db = harness.db
    hr = ObjectId((await admin.post("/api/v1/departments", json={"name": "HR"})).json()["id"])
    stores = ObjectId((await admin.post("/api/v1/departments", json={"name": "Stores"})).json()["id"])
    sara = (await admin.post("/api/v1/hosts", json={"name": "Sara Ahmed", "department_id": str(hr)})).json()
    sara = ObjectId(sara["id"])
    omar = ObjectId((await admin.post("/api/v1/hosts", json={"name": "Omar Latif"})).json()["id"])
    x, y = ObjectId(), ObjectId()
    await visit(db, kar(2026, 9, 2, 9), minutes=60, visitor=x, host=sara, dep=hr)
    await visit(db, kar(2026, 9, 3, 9), visitor=y, host=sara, dep=hr)                          # inside now
    await visit(db, kar(2026, 9, 4, 9), minutes=20, visitor=x, host=sara, dep=stores, dep_name="Stores")
    await visit(db, kar(2026, 9, 5, 9), minutes=40, host=None, host_name="Imran Ali", dep=stores, dep_name="Stores")
    await visit(db, kar(2026, 8, 25, 9), host=omar, host_name="Omar Latif", dep=hr)            # inside since August
    await visit(db, kar(2026, 10, 2, 9), minutes=5, host=sara, dep=hr)                         # after the range

    rows, total, truncated = await svc.host_report(db, SEPT, department_id=None, limit=100)
    got = [(h["host"]["name"], h["host_unlisted"], h["department"]["name"], h["visits"], h["completed_visits"],
            h["inside_now"]) for h in rows]
    assert got == [("Sara Ahmed", False, "HR", 2, 1, 1), ("Imran Ali", True, "Stores", 1, 1, 0),
                   ("Sara Ahmed", False, "Stores", 1, 1, 0), ("Omar Latif", False, "HR", 0, 0, 1)]
    assert (total, truncated) == (4, False) and rows[1]["host"]["id"] is None
    only_hr, *_ = await svc.host_report(db, SEPT, department_id=hr, limit=100)
    assert {(h["host"]["name"], h["visits"]) for h in only_hr} == {("Sara Ahmed", 2), ("Omar Latif", 0)}
    top, total, truncated = await svc.host_report(db, SEPT, department_id=None, limit=1)
    assert (len(top), total, truncated) == (1, 4, True)

    rows, total, _ = await svc.department_report(db, SEPT, limit=100)
    got = {d["department"]["name"]: (d["visits"], d["completed_visits"], d["unique_visitors"],
                                     d["avg_duration_minutes"], d["inside_now"]) for d in rows}
    assert got == {"HR": (2, 1, 2, 60, 2), "Stores": (2, 2, 2, 30, 0)} and total == 2
    # A renamed department shows its current name.
    await admin.patch(f"/api/v1/departments/{stores}", json={"name": "Warehouse"})
    rows, *_ = await svc.department_report(db, SEPT, limit=100)
    assert {d["department"]["name"] for d in rows} == {"HR", "Warehouse"}


async def test_a_visit_without_department_is_handled(harness):
    await visit(harness.db, kar(2026, 9, 2, 9), minutes=10, dep=None, dep_name=None)
    rows, *_ = await svc.department_report(harness.db, SEPT, limit=100)
    assert rows == [{"department": {"id": None, "name": None}, "visits": 1, "completed_visits": 1, "unique_visitors": 1,
                     "avg_duration_minutes": 10, "inside_now": 0}]
    hosts, *_ = await svc.host_report(harness.db, SEPT, department_id=None, limit=100)
    assert hosts[0]["department"] == {"id": None, "name": None}


async def test_hosts_and_departments_over_http(admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await check_in(guard, v["id"], directory)
    hosts = (await admin.get("/api/v1/reports/hosts")).json()
    assert hosts["items"][0]["host"]["name"] == "Sara Ahmed" and hosts["items"][0]["inside_now"] == 1
    deps = (await admin.get("/api/v1/reports/departments")).json()
    assert deps["items"][0]["department"]["name"] == "HR" and deps["items"][0]["visits"] == 1
    for body in (hosts, deps):
        assert set(body) == {"range", "items", "total", "truncated"} and "email" not in str(body)


# ------------------------------------------------------------------------------------------ guards
async def test_guard_activity(harness):
    db = harness.db
    ann = (await harness.create_user("ann", "Correct-Horse-9-Battery", "GUARD", display_name="Ann Guard"))["_id"]
    bob = (await harness.create_user("bob", "Correct-Horse-9-Battery", "GUARD", display_name="Bob Guard"))["_id"]
    await visit(db, kar(2026, 9, 2, 9), minutes=30, by=ann, out_by=bob)          # in by Ann, out by Bob
    await visit(db, kar(2026, 9, 3, 9), by=ann)                                  # inside now
    await visit(db, kar(2026, 8, 30, 9), by=bob, out_by=ann, out_at=kar(2026, 9, 1, 10))   # out within the range
    await visit(db, kar(2026, 8, 10, 9), by=bob)                                 # inside since August
    await visit(db, kar(2026, 10, 5, 9), minutes=5, by=ann)                      # after the range
    await denial(db, kar(2026, 9, 4, 9), operator_id=ann, operator_name="Ann Guard")
    await denial(db, kar(2026, 9, 4, 10), operator_id=ann, reason="OTHER")      # a denial, not a watchlist match
    await denial(db, kar(2026, 9, 5, 9), source="audit_backfill", operator_id=None, operator_username="oldguard")
    await denial(db, kar(2026, 10, 9, 9), operator_id=ann)                       # after the range

    rows, total, truncated = await svc.guard_report(db, SEPT, limit=100)
    got = {g["guard"]["name"]: (g["check_ins"], g["check_outs"], g["inside_now"], g["denied_entries"],
                                g["watchlist_matches"]) for g in rows}
    assert got == {"Ann Guard": (2, 1, 1, 2, 1), "Bob Guard": (0, 1, 1, 0, 0), "oldguard": (0, 0, 0, 1, 1)}
    assert (total, truncated) == (3, False)
    ann_row = next(g for g in rows if g["guard"]["name"] == "Ann Guard")
    assert ann_row["guard"] == {"id": str(ann), "name": "Ann Guard", "role": "GUARD", "is_active": True}
    unknown = next(g for g in rows if g["guard"]["id"] is None)
    assert unknown["guard"]["role"] is None


async def test_guards_over_http_expose_no_account_secrets(admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    await check_in(guard, v["id"], directory)
    body = (await admin.get("/api/v1/reports/guards")).json()
    [row] = body["items"]
    assert row["guard"]["name"] == "Guard1" and row["check_ins"] == 1 and row["inside_now"] == 1
    assert set(row["guard"]) == {"id", "name", "role", "is_active"}
    for secret in ("password", "hash", "argon", "session", "token", "failed_login", "locked"):
        assert secret not in str(body).lower(), secret


# ------------------------------------------------------------------------------------------ currently inside
async def test_currently_inside_is_the_current_state(harness, admin, guard, directory):  # noqa: F811
    db = harness.db
    old = await visit(db, datetime.now(UTC) - timedelta(days=40))                # inside for 40 days
    recent = await visit(db, datetime.now(UTC) - timedelta(minutes=30))
    await visit(db, datetime.now(UTC) - timedelta(hours=2), minutes=30)            # checked out: excluded
    v = await new_visitor(guard)
    live = (await check_in(guard, v["id"], directory)).json()

    # Date parameters mean nothing here: the report never drops someone who is still inside.
    params = {"range": "custom", "from": "2026-01-01", "to": "2026-01-02"}
    body = (await admin.get("/api/v1/reports/inside", params=params)).json()
    assert body["total"] == 3 and set(body) == {"generated_at", "items", "total", "next_cursor"}
    ids = [i["id"] for i in body["items"]]
    assert ids == [str(old["_id"]), str(recent["_id"]), live["id"]]              # longest inside first
    assert body["items"][0]["duration_minutes"] >= 40 * 24 * 60
    assert 29 <= body["items"][1]["duration_minutes"] <= 31
    row = body["items"][2]
    assert row["id_number"] == "***********67-1" and row["phone"] == "*******4567" and row["status"] == "CHECKED_IN"
    assert row["checked_in_by"]["name"] == "Guard1" and row["check_out_at"] is None
    for secret in (CNIC, "03001234567", "Laptop", "token"):
        assert secret not in str(body), secret
    newest = (await admin.get("/api/v1/reports/inside", params={"sort": "check_in_desc"})).json()
    assert [i["id"] for i in newest["items"]] == list(reversed(ids))
    only_host = (await admin.get("/api/v1/reports/inside", params={"host_id": directory["host"]["id"]})).json()
    assert [i["id"] for i in only_host["items"]] == [live["id"]]


async def test_currently_inside_pages(harness, admin):
    for i in range(5):
        await visit(harness.db, datetime.now(UTC) - timedelta(minutes=10 * (i + 1)))
    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        body = (await admin.get("/api/v1/reports/inside", params=params)).json()
        seen += [i["id"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 5


async def test_only_the_visits_inside_can_be_listed_without_a_range(harness):
    from app.schemas.reports import VisitReportSort
    with pytest.raises(ValueError):
        await svc.visit_report(harness.db, VisitFilter(), sort=VisitReportSort.CHECK_IN_ASC, cursor=None, limit=5,
                               bounded=False)


# ------------------------------------------------------------------------------------------ denials
async def test_denials_from_every_source(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    entry = await ban(harness)
    ok = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2")
    await check_in(guard, ok["id"], directory)                                    # a successful visit: not listed
    assert (await check_in(guard, v["id"], directory)).status_code == 403          # check-in refusal
    await lookup(guard)                                                           # lookup refusal
    old = datetime.now(UTC) - timedelta(minutes=5)
    await harness.db.audit_logs.insert_one({                                     # an older refusal, rebuilt
        "timestamp": old, "action": "WATCHLIST_MATCH", "result": "SUCCESS",
        "actor": {"user_id": ObjectId(), "username": "oldguard"},
        "resource": {"type": "visitor", "id": ObjectId(v["id"])},
        "metadata": {"watchlist_id": entry["_id"], "gate_id": ObjectId(directory["gate"]["id"]),
                     "identifier": "CNIC:***********67-1"}})
    assert (await denials_svc.backfill_from_audit(harness.db)).created == 1

    body = (await admin.get("/api/v1/reports/denials")).json()
    assert (body["denied_entries"], body["watchlist_matches"], body["total"]) == (3, 3, 3)
    assert [i["source"] for i in body["items"]] == ["lookup", "check_in", "audit_backfill"]       # newest first
    rebuilt = body["items"][2]
    assert rebuilt["visitor"] == {"id": v["id"], "name": "Ali Khan"}                               # current name
    assert rebuilt["gate"]["name"] == "Main Gate" and rebuilt["operator"]["name"] == "oldguard"   # recorded name
    assert rebuilt["current_names"] == ["visitor", "gate"]
    refused = body["items"][1]
    assert refused["current_names"] == [] and refused["operator"]["name"] == "Guard1"
    assert refused["watchlist"] == {"id": str(entry["_id"]), "reason": "Theft of property."}
    assert refused["identifier"] == "CNIC:***********67-1" and refused["reason_code"] == "OFFICIAL_MEETING"
    assert set(refused) == {"id", "at", "reason", "reason_code", "source", "visitor", "identifier", "watchlist", "gate",
                            "operator", "current_names"}
    for secret in (CNIC, CNIC.replace("-", ""), "03001234567", "Laptop", "reason_note", "source_audit_id", "photo"):
        assert secret not in str(body), secret
    # Audit entries are never listed or counted: only entry_denials.
    assert await harness.db.audit_logs.count_documents({"action": "WATCHLIST_MATCH"}) == 3

    by_source = (await admin.get("/api/v1/reports/denials", params={"source": "lookup"})).json()
    assert [i["source"] for i in by_source["items"]] == ["lookup"] and by_source["denied_entries"] == 3
    me = await harness.db.users.find_one({"username": "guard1"})
    mine = (await admin.get("/api/v1/reports/denials", params={"guard_id": str(me["_id"])})).json()
    assert mine["total"] == 2


async def test_denial_counts_keep_reasons_apart_and_follow_the_range(harness):
    db = harness.db
    r = custom(date(2026, 9, 10), date(2026, 9, 10))
    await denial(db, r.start)                                    # exactly at the start: in
    await denial(db, r.end - timedelta(milliseconds=1), reason="OTHER")   # a denial but not a watchlist match
    await denial(db, r.end)                                      # exactly at the end: out
    await denial(db, r.start - timedelta(milliseconds=1))        # just before: out
    rows, cursor, total = await svc.denial_report(db, r, source=None, operator_id=None, gate_id=None, cursor=None,
                                                  limit=25)
    counts = await svc.security_counts(db, r.start, r.end)
    assert (total, counts.denied_entries, counts.watchlist_matches) == (2, 2, 1)
    assert [row["reason"] for row in rows] == ["OTHER", "WATCHLIST"] and cursor is None


async def test_denials_page_newest_first(harness):
    for i in range(5):
        await denial(harness.db, kar(2026, 9, 10, 9) + timedelta(minutes=i % 2))      # ties on the time
    seen, cursor = [], None
    while True:
        rows, cursor, total = await svc.denial_report(harness.db, custom(date(2026, 9, 10), date(2026, 9, 10)),
                                                      source=None, operator_id=None, gate_id=None, cursor=cursor,
                                                      limit=2)
        seen += [r["id"] for r in rows]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 5 == total


# ------------------------------------------------------------------------------------------ indexes
async def test_the_report_queries_use_indexes(harness):
    db = harness.db
    for i in range(300):
        await visit(db, kar(2026, 8, 1) + timedelta(hours=7 * i), minutes=5 if i % 5 else None)
        await denial(db, kar(2026, 8, 1) + timedelta(hours=7 * i))
    window = {"$gte": kar(2026, 9, 1), "$lt": kar(2026, 9, 3)}
    shapes = {
        "range (summary, hosts, departments, check-ins)": (db.visits, {"check_in_at": window}, {"check_in"}),
        "inside now": (db.visits, {"status": "CHECKED_IN"}, {"status_check_in"}),
        "check-outs by time": (db.visits, {"check_out_at": {"$type": "date"} | window}, {"check_out"}),
        "denials": (db.entry_denials, {"at": window}, {"newest_first"}),
    }
    for name, (collection, query, expected) in shapes.items():
        plan = (await collection.find(query).explain())["queryPlanner"]["winningPlan"]
        assert _plan_indexes(plan) == expected, name
