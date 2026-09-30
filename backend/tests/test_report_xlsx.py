"""Reports step 8: XLSX exports. The same rows and columns as the CSV (same filters, range, masking),
as a real workbook; administrators only. Read back with the standard library (zipfile + XML) only."""
import io
import re
import tempfile
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree

import pytest
from bson import ObjectId

from app.services import report_exports as exports
from app.services import reports as svc
from tests.conftest import make_settings
from tests.test_entry_denials import ban, lookup
from tests.test_report_endpoints import visit
from tests.test_report_exports import HEADERS, REPORTS, parse, people  # noqa: F401 - fixture
from tests.test_visitors import CNIC
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
BASE = "/api/v1/reports"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
DATE_HEADERS = {"Check-in", "Check-out", "First visit", "Last visit", "Time"}
EXCEL_EPOCH = datetime(1899, 12, 30)


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n - 1


def read_xlsx(content: bytes) -> dict[str, list[list]]:
    """{sheet name: rows of cell values} (text as str, numbers as float), plus the raw sheet XML under
    "_xml:<name>" for checks on cell types."""
    book = zipfile.ZipFile(io.BytesIO(content))
    assert book.testzip() is None and "[Content_Types].xml" in book.namelist()
    shared = []
    if "xl/sharedStrings.xml" in book.namelist():
        root = ElementTree.fromstring(book.read("xl/sharedStrings.xml"))
        shared = ["".join(t.text or "" for t in si.iter(f"{{{NS['m']}}}t")) for si in root.findall("m:si", NS)]
    rels = {r.get("Id"): r.get("Target") for r in ElementTree.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
    out: dict[str, list[list]] = {}
    for sheet in ElementTree.fromstring(book.read("xl/workbook.xml")).find("m:sheets", NS):
        target = rels[sheet.get(f"{{{NS['r']}}}id")]
        xml = book.read("xl/" + target.lstrip("/").removeprefix("xl/"))
        rows = []
        for row in ElementTree.fromstring(xml).iter(f"{{{NS['m']}}}row"):
            cells: dict[int, object] = {}
            for c in row.findall("m:c", NS):
                kind, v = c.get("t"), c.find("m:v", NS)
                if kind == "s":
                    value = shared[int(v.text)]
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in c.iter(f"{{{NS['m']}}}t"))
                elif kind == "str":
                    value = v.text
                else:
                    value = float(v.text) if v is not None else None
                cells[_col(c.get("r"))] = value
            rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
        out[sheet.get("name")] = rows
        out["_xml:" + sheet.get("name")] = xml.decode()
    return out


def as_date(serial: float) -> datetime:
    return EXCEL_EPOCH + timedelta(days=serial)


def normalised_xlsx(rows: list[list]) -> list[dict]:
    header = rows[0]
    out = []
    for row in rows[1:]:
        row = row + [None] * (len(header) - len(row))
        item = {}
        for h, v in zip(header, row, strict=True):
            if v is None:
                item[h] = ""
            elif h in DATE_HEADERS:
                item[h] = as_date(v).replace(microsecond=0).isoformat(timespec="minutes")
            elif isinstance(v, float):
                item[h] = str(int(v))
            else:
                item[h] = v
        out.append(item)
    return out


def normalised_csv(rows: list[dict]) -> list[dict]:
    """The CSV's values as they would read in the workbook: dates as local wall-clock minutes, and without
    the CSV's apostrophe in front of formula-like text (the workbook stores such text as text)."""
    out = []
    for row in rows:
        item = {}
        for h, v in row.items():
            if h in DATE_HEADERS and v:
                v = datetime.fromisoformat(v).replace(tzinfo=None).isoformat(timespec="minutes")
            elif v.startswith("'") and v[1:2] in ("=", "+", "-", "@", "\t", "\r"):
                v = v[1:]
            item[h] = v
        out.append(item)
    return out


async def xlsx(client, report, **params):
    return await client.get(f"{BASE}/{report}/export", params={"format": "xlsx"} | params)


async def csv_(client, report, **params):
    return await client.get(f"{BASE}/{report}/export", params={"format": "csv"} | params)


def report_rows(r) -> list[list]:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == exports.XLSX_TYPE
    book = read_xlsx(r.content)
    return book[exports.SHEET_TITLES[_report_of(r)]]


def _report_of(r) -> str:
    return re.search(r"/reports/(\w+)/export", str(r.request.url)).group(1)


def leftover_files() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("cgvms-report-*.xlsx")}


# ------------------------------------------------------------------------------------------ access
@pytest.mark.parametrize("report", REPORTS)
async def test_access(harness, admin, guard, report):
    assert (await harness.client().get(f"{BASE}/{report}/export", params={"format": "xlsx"})).status_code == 401
    r = await xlsx(guard, report)
    assert r.status_code == 403 and r.headers["content-type"].startswith("application/json")
    assert (await xlsx(admin, report)).status_code == 200


# ------------------------------------------------------------------------------------------ the file
@pytest.mark.parametrize("report", REPORTS)
async def test_every_report_is_a_valid_workbook_even_when_empty(admin, report):
    before = leftover_files()
    r = await xlsx(admin, report, range="custom", **{"from": "2020-01-01", "to": "2020-01-31"})
    assert r.headers["cache-control"] == "no-store, private"
    disposition = r.headers["content-disposition"]
    if report == "inside":
        assert re.fullmatch(r'attachment; filename="century-gate-inside-\d{4}-\d{2}-\d{2}-\d{4}\.xlsx"', disposition)
    else:
        assert disposition == f'attachment; filename="century-gate-{report}-2020-01-01_to_2020-01-31.xlsx"'
    book = read_xlsx(r.content)
    sheet = book[exports.SHEET_TITLES[report]]
    assert sheet[0] == HEADERS[report]
    if report != "inside":
        assert len(sheet) == 1                                               # headers only, still a workbook
    about = dict((row[0], row[1]) for row in book["About"])
    assert about["Time zone"] == "Asia/Karachi" and about["Privacy"] == "ID numbers and phone numbers are masked."
    assert about["Period"] == ("Current state (no date range)" if report == "inside" else "2020-01-01 to 2020-01-31")
    assert leftover_files() <= before                                       # the temporary file is deleted


async def test_the_workbook_types_its_cells(admin, people):  # noqa: F811
    r = await xlsx(admin, "visits", status="CHECKED_OUT")
    book = read_xlsx(r.content)
    header, row = book["Visits"][0], book["Visits"][1]
    cell = dict(zip(header, row, strict=False))
    assert isinstance(cell["Duration (minutes)"], float)                      # a number, not text
    check_in_at = as_date(cell["Check-in"])                                  # a real Excel date-time
    screen = (await admin.get(f"{BASE}/visits", params={"status": "CHECKED_OUT"})).json()["items"][0]
    expected = datetime.fromisoformat(screen["check_in_at"].replace("Z", "+00:00")) + timedelta(hours=5)
    assert abs((check_in_at - expected.replace(tzinfo=None)).total_seconds()) < 1   # Karachi wall-clock time
    assert "<f>" not in book["_xml:Visits"]                                  # never a formula
    about = dict((row[0], row[1]) for row in book["About"])
    assert (about["Rows"], about["Filters used"]) == ("1", "status")


# ------------------------------------------------------------------------------------------ same data as the CSV
async def test_the_visit_export_matches_the_csv_for_every_filter(admin, people):  # noqa: F811
    users = people["users"]
    cases = [
        {}, {"status": "CHECKED_IN"}, {"q": "alia"}, {"q": "3520112345671"}, {"host_id": people["host"]["id"]},
        {"department_id": people["other_dep"]["id"]}, {"gate_id": people["gate"]["id"]},
        {"guard_id": str(users["admin"])}, {"reason_code": "DELIVERY"}, {"range": "yesterday"},
        {"sort": "duration_desc"},
    ]
    for params in cases:
        from_xlsx = normalised_xlsx(report_rows(await xlsx(admin, "visits", **params)))
        from_csv = normalised_csv(parse(await csv_(admin, "visits", **params)))
        assert from_xlsx == from_csv, params


async def test_every_other_export_matches_its_csv(harness, admin, guard, people):  # noqa: F811
    await ban(harness, number="35201-7654321-2")
    await lookup(admin, "35201-7654321-2")                                    # one refused entry
    for report, params in (("visitors", {}), ("visitors", {"q": "alia"}), ("hosts", {}),
                           ("hosts", {"department_id": people["other_dep"]["id"]}), ("departments", {}),
                           ("guards", {}), ("inside", {}), ("inside", {"host_id": people["host"]["id"]}),
                           ("denials", {}), ("denials", {"source": "check_in"})):
        from_xlsx = normalised_xlsx(report_rows(await xlsx(admin, report, **params)))
        from_csv = normalised_csv(parse(await csv_(admin, report, **params)))
        assert from_xlsx == from_csv, (report, params)
        assert from_xlsx or params, (report, params)                          # the unfiltered ones have rows


async def test_ranges_are_karachi_days_start_included_end_excluded(harness, admin):
    db = harness.db
    r = svc.report_range(make_settings(), "custom", date(2026, 9, 10), date(2026, 9, 11))
    first = await visit(db, r.start, minutes=5)
    last = await visit(db, r.end - timedelta(milliseconds=1), minutes=5)
    await visit(db, r.end, minutes=5)
    await visit(db, r.start - timedelta(milliseconds=1), minutes=5)
    rows = normalised_xlsx(report_rows(await xlsx(admin, "visits", range="custom",
                                                  **{"from": "2026-09-10", "to": "2026-09-11"})))
    assert [row["Visit number"] for row in rows] == [last["visit_number"], first["visit_number"]]
    assert rows[1]["Check-in"] == "2026-09-10T00:00"


# ------------------------------------------------------------------------------------------ privacy, text
async def test_workbooks_hold_nothing_private(harness, admin, people):  # noqa: F811
    await ban(harness, number="35201-7654321-2")
    await lookup(admin, "35201-7654321-2")
    ids = [people["va"]["id"], people["vb"]["id"], people["a"]["id"], people["b"]["id"],
           *(str(u) for u in people["users"].values())]
    for report in REPORTS:
        book = read_xlsx((await xlsx(admin, report)).content)
        text = str({k: v for k, v in book.items()})
        for secret in (CNIC, CNIC.replace("-", ""), "35201-7654321-2", "3520176543212", "03001234567",
                       "03217654321", "Laptop", "LEA1234", "photo", "token", "password", "session",
                       "reason_note", "source_audit_id", "metadata", *ids):
            assert secret not in text, (report, secret)
    visits = normalised_xlsx(read_xlsx((await xlsx(admin, "visits")).content)["Visits"])
    assert {v["ID number (masked)"] for v in visits} == {"***********67-1", "***********21-2"}
    assert {v["Phone (masked)"] for v in visits} == {"*******4567", "*******4321"}


async def test_formula_like_and_unicode_text_stays_text(harness, admin):
    db = harness.db
    formula = ObjectId()
    await db.departments.insert_one({"_id": formula, "name": "=cmd|' /C calc'!A0", "is_active": True,
                                     "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC)})
    await visit(db, datetime.now(UTC) - timedelta(minutes=5), minutes=1, dep=formula, visitor_name="علی خان",
                host=None, host_name="+Imran")
    book = read_xlsx((await xlsx(admin, "departments")).content)
    assert book["Departments"][1][0] == "=cmd|' /C calc'!A0"                   # exact value, stored as text
    assert "<f>" not in book["_xml:Departments"]
    visits = read_xlsx((await xlsx(admin, "visits")).content)
    assert "علی خان" in {row[1] for row in visits["Visits"][1:]}
    hosts = read_xlsx((await xlsx(admin, "hosts")).content)
    assert "+Imran" in {row[0] for row in hosts["Hosts"][1:]}


# ------------------------------------------------------------------------------------------ errors, size, audit
@pytest.mark.parametrize("params,status,code", [
    ({"format": "docx"}, 422, "validation_error"),                 # pdf is supported since step 9
    ({"format": "XLSX"}, 422, "validation_error"),
    ({"format": "xlsx", "range": "custom", "from": "2026-09-02", "to": "2026-09-01"}, 422, "invalid_range"),
    ({"format": "xlsx", "host_id": "nope"}, 422, "validation_error"),
    ({"format": "xlsx", "status": "LOST"}, 422, "validation_error"),
])
async def test_invalid_requests_answer_in_json(admin, params, status, code):
    r = await admin.get(f"{BASE}/visits/export", params=params)
    assert (r.status_code, r.json()["error"]["code"]) == (status, code)


async def test_an_export_over_the_limit_is_refused_before_any_file_is_made(harness, admin, people, monkeypatch):  # noqa: F811
    monkeypatch.setattr(exports, "EXPORT_MAX_ROWS", 1)
    before = leftover_files()
    r = await xlsx(admin, "visits")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "export_too_large")
    assert leftover_files() <= before
    assert await harness.db.audit_logs.count_documents({"action": "REPORT_EXPORTED"}) == 0


async def test_a_failure_while_building_leaves_no_file_and_no_audit(harness, admin, people, monkeypatch):  # noqa: F811
    before = leftover_files()

    async def broken(*args, **kwargs):
        raise RuntimeError("database gone")
        yield  # pragma: no cover

    monkeypatch.setattr(exports, "visit_rows", broken)
    r = await xlsx(admin, "visits")
    assert r.status_code == 500 and r.headers["content-type"].startswith("application/json")   # never a half file
    assert "database gone" not in r.text                                    # no internal detail
    assert leftover_files() <= before
    assert await harness.db.audit_logs.count_documents({"action": "REPORT_EXPORTED"}) == 0


async def test_exports_are_audited_as_xlsx(harness, admin, people):  # noqa: F811
    await xlsx(admin, "visits", q="alia", range="this_week")
    [entry] = await harness.db.audit_logs.find({"action": "REPORT_EXPORTED"}).to_list(length=5)
    assert (entry["metadata"]["format"], entry["metadata"]["rows"], entry["metadata"]["filters"]) == ("xlsx", 1, ["q"])
    assert "alia" not in str(entry).lower()
