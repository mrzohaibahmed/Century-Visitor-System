"""Reports step 6: CSV exports. Same rows as the report screens (same filters, range, sort and masking),
streamed as a download; administrators only; formula injection neutralised."""
import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from bson import ObjectId

from app.services import entry_denials as denials_svc
from app.services import report_exports as exports
from app.services import reports as svc
from tests.conftest import make_settings
from tests.test_entry_denials import ban, lookup
from tests.test_report_endpoints import denial, kar, visit
from tests.test_visitors import CNIC, new_visitor
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
BASE = "/api/v1/reports"
REPORTS = ["visits", "visitors", "hosts", "departments", "guards", "inside", "denials"]
HEADERS = {
    "visits": ["Visit number", "Visitor", "ID type", "ID number (masked)", "Phone (masked)", "Host", "Host not listed",
               "Department", "Purpose", "Gate", "Check-in", "Check-out", "Duration (minutes)", "Status",
               "Checked in by", "Checked out by"],
    "visitors": ["Visitor", "ID type", "ID number (masked)", "Phone (masked)", "Visits", "Completed visits",
                 "First visit", "Last visit", "Average duration (minutes)", "Inside now"],
    "hosts": ["Host", "Host not listed", "Department", "Visits", "Completed visits", "Inside now"],
    "departments": ["Department", "Visits", "Completed visits", "Unique visitors", "Average duration (minutes)",
                    "Inside now"],
    "guards": ["Operator", "Role", "Active", "Check-ins", "Check-outs", "Inside now", "Denied entries",
               "Watchlist matches"],
    "inside": ["Visit number", "Visitor", "ID type", "ID number (masked)", "Phone (masked)", "Host", "Department",
               "Gate", "Check-in", "Inside for (minutes)", "Checked in by"],
    "denials": ["Time", "Source", "Reason", "Purpose", "Visitor", "ID (masked)", "Watchlist reason", "Gate",
                "Operator", "Names from current records"],
}


def parse(r) -> list[dict]:
    """The CSV body as dicts (the header row checked separately)."""
    assert r.status_code == 200, r.text
    assert r.content.startswith("﻿".encode())                    # UTF-8 with a byte order mark
    return list(csv.DictReader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))


def header(r) -> list[str]:
    return next(csv.reader(io.StringIO(r.content.decode("utf-8-sig"), newline="")))


async def export(client, report, **params):
    return await client.get(f"{BASE}/{report}/export", params=params)


@pytest.fixture
async def people(harness, admin, guard, directory):  # noqa: F811
    a = await new_visitor(guard)
    b = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2", phone="0321-7654321")
    va = (await check_in(guard, a["id"], directory)).json()
    vb = (await check_in(guard, b["id"], directory, host_id=None, unlisted_host_name="Imran Ali",
                         department_id=directory["other_dep"]["id"], reason_code="DELIVERY")).json()
    await admin.post(f"/api/v1/visits/{va['id']}/check-out")
    users = {u["username"]: u["_id"] async for u in harness.db.users.find()}
    return {"a": a, "b": b, "va": va, "vb": vb, "users": users, **directory}


# ------------------------------------------------------------------------------------------ access
@pytest.mark.parametrize("report", REPORTS)
async def test_access(harness, admin, guard, report):
    assert (await harness.client().get(f"{BASE}/{report}/export")).status_code == 401
    r = await export(guard, report)
    assert r.status_code == 403 and "text/csv" not in r.headers.get("content-type", "")
    denied = await harness.db.audit_logs.find_one({"action": "ACCESS_DENIED",
                                                   "metadata.path": f"{BASE}/{report}/export"})
    assert denied["metadata"]["permission"] in ("reports:export", "reports:view")
    assert (await export(admin, report)).status_code == 200


# ------------------------------------------------------------------------------------------ headers, format
@pytest.mark.parametrize("report", REPORTS)
async def test_headers_and_empty_exports(admin, report):
    r = await export(admin, report, range="custom", **{"from": "2020-01-01", "to": "2020-01-31"})
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["cache-control"] == "no-store, private"
    disposition = r.headers["content-disposition"]
    if report == "inside":                                               # current state: named by the moment
        assert re.fullmatch(r'attachment; filename="century-gate-inside-\d{4}-\d{2}-\d{2}-\d{4}\.csv"', disposition)
    else:
        assert disposition == f'attachment; filename="century-gate-{report}-2020-01-01_to_2020-01-31.csv"'
    assert header(r) == HEADERS[report]
    if report != "inside":
        assert parse(r) == []                                            # empty: still a valid file


async def test_a_one_day_file_name_and_no_request_text_in_it(admin):
    r = await export(admin, "visits", q='x"; filename="evil.exe', range="custom", **{"from": "2026-09-30",
                                                                                     "to": "2026-09-30"})
    assert r.headers["content-disposition"] == 'attachment; filename="century-gate-visits-2026-09-30.csv"'


@pytest.mark.parametrize("params,status,code", [
    ({"format": "xls"}, 422, "validation_error"),                  # xlsx is supported since step 8
    ({"format": "docx"}, 422, "validation_error"),                 # pdf is supported since step 9
    ({"range": "custom", "from": "2026-09-02", "to": "2026-09-01"}, 422, "invalid_range"),
    ({"host_id": "nope"}, 422, "validation_error"),
])
async def test_invalid_exports_answer_in_json(admin, params, status, code):
    r = await export(admin, "visits", **params)
    assert (r.status_code, r.json()["error"]["code"]) == (status, code)


# ------------------------------------------------------------------------------------------ cells
@pytest.mark.parametrize("value,expected", [
    ("=HYPERLINK(\"http://x\")", "'=HYPERLINK(\"http://x\")"),
    ("+92300", "'+92300"),
    ("-2+3", "'-2+3"),
    ("@SUM(A1)", "'@SUM(A1)"),
    ("\tcmd", "'\tcmd"),
    ("\rcmd", "'\rcmd"),
    ("Ali Khan", "Ali Khan"),
    ("V-2026-000001", "V-2026-000001"),
    ("***********67-1", "***********67-1"),
    (42, 42), (0, 0), (True, "Yes"), (False, "No"), (None, ""),
])
def test_cells(value, expected):
    assert exports.cell(value, ZoneInfo("Asia/Karachi")) == expected


def test_times_are_written_in_the_organisation_time_zone():
    assert exports.cell(datetime(2026, 9, 30, 19, 30, tzinfo=UTC), ZoneInfo("Asia/Karachi")) == \
        "2026-10-01T00:30:00+05:00"


async def test_quotes_commas_line_breaks_unicode_and_formulas_survive(harness, admin):
    db = harness.db
    dep = ObjectId()
    await db.departments.insert_one({"_id": dep, "name": 'R&D, "Labs"\nWest', "is_active": True,
                                     "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC)})
    formula = ObjectId()
    await db.departments.insert_one({"_id": formula, "name": "=cmd|' /C calc'!A0", "is_active": True,
                                     "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC)})
    now = datetime.now(UTC) - timedelta(minutes=5)
    await visit(db, now, minutes=1, dep=dep, visitor_name="علی خان", host_name="-Imran", host=None)
    await visit(db, now, minutes=1, dep=formula, dep_name="x")
    rows = parse(await export(admin, "departments"))
    assert {r["Department"] for r in rows} == {'R&D, "Labs"\nWest', "'=cmd|' /C calc'!A0"}
    hosts = parse(await export(admin, "hosts"))
    assert "'-Imran" in {r["Host"] for r in hosts}
    visits = parse(await export(admin, "visits"))
    assert "علی خان" in {r["Visitor"] for r in visits}
    assert '"R&D, ""Labs""\nWest"' in (await export(admin, "departments")).content.decode("utf-8-sig")


# ------------------------------------------------------------------------------------------ same data as the screen
async def _numbers_json(admin, **params) -> list[str]:
    out, cursor = [], None
    while True:
        body = (await admin.get(f"{BASE}/visits", params=params | {"limit": 100} | (
            {"cursor": cursor} if cursor else {}))).json()
        out += [i["visit_number"] for i in body["items"]]
        cursor = body["next_cursor"]
        if not cursor:
            return out


async def test_the_visit_export_follows_every_filter(admin, people):
    users, va, vb = people["users"], people["va"]["visit_number"], people["vb"]["visit_number"]
    cases = [
        {}, {"status": "CHECKED_OUT"}, {"status": "CHECKED_IN"}, {"q": "alia"}, {"q": "3520112345671"},
        {"q": "0321 7654321"}, {"q": va.lower()}, {"host_id": people["host"]["id"]},
        {"department_id": people["other_dep"]["id"]}, {"gate_id": people["gate"]["id"]}, {"gate_id": "0" * 24},
        {"guard_id": str(users["admin"])}, {"guard_id": str(users["guard1"])}, {"reason_code": "DELIVERY"},
        {"range": "yesterday"}, {"sort": "check_in_asc"}, {"sort": "check_out_desc"}, {"sort": "duration_desc"},
    ]
    for params in cases:
        exported = [r["Visit number"] for r in parse(await export(admin, "visits", **params))]
        assert exported == await _numbers_json(admin, **params), params
    assert [r["Visit number"] for r in parse(await export(admin, "visits"))] == [vb, va]


async def test_the_visit_export_carries_the_screens_values(admin, people):
    [row] = parse(await export(admin, "visits", status="CHECKED_OUT"))
    screen = (await admin.get(f"{BASE}/visits", params={"status": "CHECKED_OUT"})).json()["items"][0]
    assert row["ID number (masked)"] == screen["id_number"] == "***********67-1"
    assert row["Phone (masked)"] == screen["phone"] == "*******4567"
    assert (row["Visitor"], row["Host"], row["Department"], row["Gate"]) == ("Ali Khan", "Sara Ahmed", "HR",
                                                                            "Main Gate")
    assert (row["Purpose"], row["Status"], row["Host not listed"]) == ("OFFICIAL_MEETING", "CHECKED_OUT", "No")
    assert (row["Checked in by"], row["Checked out by"]) == ("Guard1", "Admin")
    check_in_at = datetime.fromisoformat(screen["check_in_at"].replace("Z", "+00:00"))
    assert row["Check-in"] == check_in_at.astimezone(ZoneInfo("Asia/Karachi")).isoformat()
    assert row["Check-in"].endswith("+05:00") and int(row["Duration (minutes)"]) == screen["duration_minutes"]


async def test_other_exports_follow_their_filters(admin, people):
    visitors = parse(await export(admin, "visitors", q="alia"))
    assert [r["Visitor"] for r in visitors] == ["Alia Noor"] and visitors[0]["Inside now"] == "Yes"
    assert [r["Visitor"] for r in parse(await export(admin, "visitors", host_id=people["host"]["id"]))] == ["Ali Khan"]
    hosts = parse(await export(admin, "hosts", department_id=people["other_dep"]["id"]))
    assert [(r["Host"], r["Host not listed"], r["Department"]) for r in hosts] == [("Imran Ali", "Yes", "Stores")]
    inside = parse(await export(admin, "inside", host_id=people["host"]["id"]))
    assert inside == []                                                      # Sara's visitor has left
    assert [r["Visitor"] for r in parse(await export(admin, "inside", q="alia"))] == ["Alia Noor"]
    guards = {r["Operator"]: r for r in parse(await export(admin, "guards"))}
    assert (guards["Guard1"]["Check-ins"], guards["Admin"]["Check-outs"]) == ("2", "1")


async def test_ranges_are_karachi_days_start_included_end_excluded(harness, admin):
    db = harness.db
    r = svc.report_range(make_settings(), "custom", date(2026, 9, 10), date(2026, 9, 11))
    assert (r.start, r.end) == (kar(2026, 9, 10), kar(2026, 9, 12))
    first = await visit(db, r.start, minutes=5)                                 # 00:00 on the 10th: in
    last = await visit(db, r.end - timedelta(milliseconds=1), minutes=5)       # 23:59:59.999 on the 11th: in
    await visit(db, r.end, minutes=5)                                         # 00:00 on the 12th: out
    await visit(db, r.start - timedelta(milliseconds=1), minutes=5)            # 23:59:59.999 on the 9th: out
    rows = parse(await export(admin, "visits", range="custom", **{"from": "2026-09-10", "to": "2026-09-11"}))
    assert [row["Visit number"] for row in rows] == [last["visit_number"], first["visit_number"]]
    assert rows[1]["Check-in"] == "2026-09-10T00:00:00+05:00"


async def test_grouped_exports_are_never_cut_to_the_screen_limit(harness, admin, monkeypatch):
    for i in range(3):
        await visit(harness.db, datetime.now(UTC) - timedelta(minutes=i + 1), minutes=1, host=ObjectId(),
                    host_name=f"Host {chr(65 + i)}")
    monkeypatch.setattr(svc, "GROUP_LIMIT_MAX", 1)
    assert (await admin.get(f"{BASE}/hosts")).json()["truncated"] is True
    assert len(parse(await export(admin, "hosts"))) == 3


async def test_large_exports_stream_every_row_in_order(harness, admin):
    start = datetime.now(UTC) - timedelta(hours=10)
    for i in range(250):                                                     # 3 pages, 2 chunks
        await visit(harness.db, start + timedelta(seconds=i), minutes=1)
    rows = parse(await export(admin, "visits"))
    assert len(rows) == len({r["Visit number"] for r in rows}) == 250
    assert [r["Visit number"] for r in rows] == await _numbers_json(admin)


async def test_an_export_over_the_limit_is_refused_not_cut(harness, admin, people, monkeypatch):
    monkeypatch.setattr(exports, "EXPORT_MAX_ROWS", 1)
    r = await export(admin, "visits")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "export_too_large")
    assert await harness.db.audit_logs.count_documents({"action": "REPORT_EXPORTED"}) == 0


async def test_a_too_broad_search_is_refused_before_the_download(admin, people, monkeypatch):
    monkeypatch.setattr(svc, "REPORT_VISITOR_MATCHES", 1)
    r = await export(admin, "visits", q="a")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "search_too_broad")


# ------------------------------------------------------------------------------------------ privacy
async def test_exports_hold_nothing_private(harness, admin, people):
    await ban(harness, number="35201-7654321-2")
    await lookup(admin, "35201-7654321-2")                                   # a refused lookup: in the denials
    ids = [people["va"]["id"], people["vb"]["id"], people["a"]["id"], people["b"]["id"], people["host"]["id"],
           *(str(u) for u in people["users"].values())]
    for report in REPORTS:
        text = (await export(admin, report)).content.decode("utf-8-sig")
        for secret in (CNIC, CNIC.replace("-", ""), "35201-7654321-2", "3520176543212", "03001234567",
                       "03217654321", "Laptop", "LEA1234", "photo", "token", "password", "hash", "session",
                       "reason_note", "source_audit_id", "metadata", *ids):
            assert secret not in text, (report, secret)


# ------------------------------------------------------------------------------------------ current state, denials
async def test_the_inside_export_is_the_current_state(harness, admin):
    old = await visit(harness.db, datetime.now(UTC) - timedelta(days=40))
    await visit(harness.db, datetime.now(UTC) - timedelta(hours=1), minutes=10)     # left: not inside
    rows = parse(await export(admin, "inside", range="custom", **{"from": "2020-01-01", "to": "2020-01-02"}))
    assert [r["Visit number"] for r in rows] == [old["visit_number"]]
    assert int(rows[0]["Inside for (minutes)"]) >= 40 * 24 * 60


async def test_the_denial_export(harness, admin, guard, directory):  # noqa: F811
    v = await new_visitor(guard)
    entry = await ban(harness, reason='Theft, "repeated"\n=HYPERLINK("x")')
    ok = await new_visitor(guard, name="Alia Noor", number="35201-7654321-2")
    await check_in(guard, ok["id"], directory)                                  # a visit: never a denial
    await check_in(guard, v["id"], directory)                                   # refused at check-in
    await lookup(guard)                                                        # refused at the lookup
    audit_only = {"timestamp": datetime.now(UTC) - timedelta(minutes=5), "action": "WATCHLIST_MATCH",
                  "result": "SUCCESS", "actor": {"user_id": ObjectId(), "username": "oldguard"},
                  "resource": {"type": "visitor", "id": ObjectId(v["id"])},
                  "metadata": {"watchlist_id": entry["_id"], "gate_id": None, "identifier": "CNIC:***********67-1"}}
    await harness.db.audit_logs.insert_one(audit_only)
    rows = parse(await export(admin, "denials"))
    assert [r["Source"] for r in rows] == ["lookup", "check_in"]                # audit-only: not a denial yet
    await denials_svc.backfill_from_audit(harness.db)
    rows = parse(await export(admin, "denials"))
    assert [r["Source"] for r in rows] == ["lookup", "check_in", "audit_backfill"]
    assert all(r["Reason"] == "WATCHLIST" and r["ID (masked)"] == "CNIC:***********67-1" for r in rows)
    assert rows[1]["Watchlist reason"] == 'Theft, "repeated"\n=HYPERLINK("x")'   # a formula only at the start
    assert (rows[1]["Operator"], rows[1]["Gate"], rows[1]["Purpose"]) == ("Guard1", "Main Gate", "OFFICIAL_MEETING")
    assert rows[2]["Operator"] == "oldguard" and rows[2]["Names from current records"] == "visitor"
    assert len(rows) == (await admin.get(f"{BASE}/denials")).json()["total"]
    assert [r["Source"] for r in parse(await export(admin, "denials", source="lookup"))] == ["lookup"]


async def test_a_denial_reason_that_looks_like_a_formula_is_neutralised(harness, admin):
    await harness.db.watchlist.insert_one({"_id": (w := ObjectId()), "identifier": "CNIC:1", "identity": {
        "type": "CNIC", "number": "1"}, "reason": "@SUM(1+1)", "is_active": False, "created_by": ObjectId(),
        "created_at": datetime.now(UTC)})
    await denial(harness.db, datetime.now(UTC) - timedelta(minutes=1), watchlist_id=w)
    [row] = parse(await export(admin, "denials"))
    assert row["Watchlist reason"] == "'@SUM(1+1)"


# ------------------------------------------------------------------------------------------ audit
async def test_exports_are_audited_without_their_contents(harness, admin, people):
    await export(admin, "visits", q="alia", status="CHECKED_IN", range="this_week")
    [entry] = await harness.db.audit_logs.find({"action": "REPORT_EXPORTED"}).to_list(length=5)
    meta = entry["metadata"]
    assert (meta["report"], meta["format"], meta["rows"], meta["filters"]) == ("visits", "csv", 1, ["q", "status"])
    assert meta["range"]["preset"] == "this_week" and entry["actor"]["username"] == "admin"
    assert "alia" not in str(entry).lower() and "Alia" not in str(entry) and CNIC not in str(entry)
