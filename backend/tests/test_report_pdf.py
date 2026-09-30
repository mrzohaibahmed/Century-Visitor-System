"""Reports step 9: PDF exports. The same rows and columns as the CSV and XLSX (same filters, range, masking),
drawn as a printable table; administrators only. What is drawn is recorded straight from the page canvas."""
import re
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from bson import ObjectId

from app.services import report_exports as exports
from app.services import report_pdf as rp
from app.services import reports as svc
from tests.conftest import make_settings
from tests.test_entry_denials import ban, lookup
from tests.test_report_endpoints import visit
from tests.test_report_exports import HEADERS, REPORTS, parse, people  # noqa: F401 - fixture
from tests.test_report_xlsx import normalised_xlsx, read_xlsx
from tests.test_visitors import CNIC
from tests.test_visits import check_in, directory  # noqa: F401 - fixture

pytestmark = pytest.mark.anyio
BASE = "/api/v1/reports"
DATE_HEADERS = {"Check-in", "Check-out", "First visit", "Last visit", "Time"}


@pytest.fixture
def drawn(monkeypatch):
    """Every string drawn on a PDF page: (method, font, text)."""
    from reportlab.pdfgen.canvas import Canvas
    seen: list[tuple[str, str, str]] = []
    for name in ("drawString", "drawRightString"):
        original = getattr(Canvas, name)

        def spy(self, x, y, text, *args, _original=original, _name=name, **kwargs):
            seen.append((_name, self._fontname, str(text)))
            return _original(self, x, y, text, *args, **kwargs)

        monkeypatch.setattr(Canvas, name, spy)
    return seen


@pytest.fixture
def pdf_rows(monkeypatch):
    """The table rows (cell texts) handed to the PDF table, in order."""
    rows: list[list[str]] = []
    original = rp.PdfTable.add_rows

    def spy(self, batch):
        rows.extend(list(r) for r in batch)
        return original(self, batch)

    monkeypatch.setattr(rp.PdfTable, "add_rows", spy)
    return rows


async def pdf(client, report, **params):
    return await client.get(f"{BASE}/{report}/export", params={"format": "pdf"} | params)


def assert_pdf(r) -> bytes:
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"] == "no-store, private"
    body = r.content
    assert body.startswith(b"%PDF-") and body.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type /Page\b", body)) >= 1
    return body


def csv_as_pdf_text(rows: list[dict]) -> list[list[str]]:
    """The CSV rows as the PDF prints them: dates as local "YYYY-MM-DD HH:MM", formula-like text without
    the CSV's apostrophe (a PDF runs nothing)."""
    out = []
    for row in rows:
        cells = []
        for h, v in row.items():
            if h in DATE_HEADERS and v:
                v = datetime.fromisoformat(v).strftime("%Y-%m-%d %H:%M")
            elif v.startswith("'") and v[1:2] in ("=", "+", "-", "@", "\t", "\r"):
                v = v[1:]
            cells.append(v)
        out.append(cells)
    return out


def xlsx_as_pdf_text(rows: list[dict]) -> list[list[str]]:
    return [[v.replace("T", " ") if h in DATE_HEADERS else v for h, v in row.items()] for row in rows]


def leftover_files() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("cgvms-report-*.pdf")}


# ------------------------------------------------------------------------------------------ access
@pytest.mark.parametrize("report", REPORTS)
async def test_access(harness, admin, guard, report):
    assert (await harness.client().get(f"{BASE}/{report}/export", params={"format": "pdf"})).status_code == 401
    r = await pdf(guard, report)
    assert r.status_code == 403 and r.headers["content-type"].startswith("application/json")
    assert_pdf(await pdf(admin, report))


# ------------------------------------------------------------------------------------------ the file
@pytest.mark.parametrize("report", REPORTS)
async def test_every_report_is_a_valid_pdf_even_when_empty(admin, report, drawn):
    before = leftover_files()
    r = await pdf(admin, report, range="custom", **{"from": "2020-01-01", "to": "2020-01-31"})
    assert_pdf(r)
    disposition = r.headers["content-disposition"]
    if report == "inside":
        assert re.fullmatch(r'attachment; filename="century-gate-inside-\d{4}-\d{2}-\d{2}-\d{4}\.pdf"', disposition)
    else:
        assert disposition == f'attachment; filename="century-gate-{report}-2020-01-01_to_2020-01-31.pdf"'
    texts = [t for _, _, t in drawn]
    assert texts[0] == exports.SHEET_TITLES[report]                        # the title first
    assert "Asia/Karachi" in texts and "ID numbers and phone numbers are masked." in texts
    assert ("Current state (no date range)" if report == "inside" else "2020-01-01 to 2020-01-31") in texts
    headings = " ".join(t for _, font, t in drawn if font == rp.BOLD)
    for header in HEADERS[report]:
        assert all(word in headings for word in header.split()), header    # every column heading is drawn
    if report != "inside":
        assert "No rows match this report." in texts
    assert "Page 1" in texts
    assert leftover_files() <= before                                       # the temporary file is deleted


def test_orientation_follows_the_table_width(tmp_path):
    rp.ensure_fonts()
    wide = rp.PdfTable(str(tmp_path / "a.pdf"), exports.VISIT_COLUMNS, title="Visits", about=[])
    narrow = rp.PdfTable(str(tmp_path / "b.pdf"), exports.HOST_COLUMNS, title="Hosts", about=[])
    assert wide.page_w > wide.page_h and narrow.page_w < narrow.page_h
    for table in (wide, narrow):
        table.finish()


def test_long_text_wraps_inside_its_column(tmp_path):
    rp.ensure_fonts()
    table = rp.PdfTable(str(tmp_path / "c.pdf"), exports.DENIAL_COLUMNS, title="Refused entries", about=[])
    width = table.widths[6]                                                 # "Watchlist reason"
    text = "Theft of property from the stores on several occasions, " * 6 + "X" * 300
    lines = table._wrap(text, rp.BODY, width)
    assert len(lines) > 3
    assert all(table._width(line, rp.BODY) <= width - 2 * table.PAD for line in lines)
    assert "".join(lines).replace(" ", "") == text.replace(" ", "")          # nothing lost
    row = ["2026-09-30 10:00", "check_in", "WATCHLIST", "", "Ali Khan", "CNIC:*", text, "Gate", "G", ""]
    table.add_rows([row] * 40)
    table.finish()                                                          # a tall row across pages: no error
    assert table.page >= 2


# ------------------------------------------------------------------------------------------ same data as CSV and XLSX
async def test_the_visit_pdf_matches_csv_and_xlsx_for_every_filter(admin, people, pdf_rows):  # noqa: F811
    users = people["users"]
    cases = [
        {}, {"status": "CHECKED_IN"}, {"q": "alia"}, {"q": "3520112345671"}, {"host_id": people["host"]["id"]},
        {"department_id": people["other_dep"]["id"]}, {"gate_id": people["gate"]["id"]},
        {"guard_id": str(users["admin"])}, {"reason_code": "DELIVERY"}, {"range": "yesterday"},
        {"sort": "duration_desc"},
    ]
    for params in cases:
        pdf_rows.clear()
        assert_pdf(await pdf(admin, "visits", **params))
        from_csv = csv_as_pdf_text(parse(await admin.get(f"{BASE}/visits/export", params={"format": "csv"} | params)))
        xlsx = await admin.get(f"{BASE}/visits/export", params={"format": "xlsx"} | params)
        from_xlsx = xlsx_as_pdf_text(normalised_xlsx(read_xlsx(xlsx.content)["Visits"]))
        assert pdf_rows == from_csv == from_xlsx, params


async def test_every_other_pdf_matches_its_csv(harness, admin, people, pdf_rows):  # noqa: F811
    await ban(harness, number="35201-7654321-2")
    await lookup(admin, "35201-7654321-2")
    for report, params in (("visitors", {}), ("visitors", {"q": "alia"}), ("hosts", {}),
                           ("hosts", {"department_id": people["other_dep"]["id"]}), ("departments", {}),
                           ("guards", {}), ("inside", {}), ("inside", {"host_id": people["host"]["id"]}),
                           ("denials", {}), ("denials", {"source": "check_in"})):
        pdf_rows.clear()
        assert_pdf(await pdf(admin, report, **params))
        from_csv = csv_as_pdf_text(parse(await admin.get(f"{BASE}/{report}/export", params={"format": "csv"} | params)))
        assert pdf_rows == from_csv, (report, params)
        assert pdf_rows or params, (report, params)


async def test_ranges_are_karachi_days_start_included_end_excluded(harness, admin, pdf_rows):
    db = harness.db
    r = svc.report_range(make_settings(), "custom", date(2026, 9, 10), date(2026, 9, 11))
    first = await visit(db, r.start, minutes=5)
    last = await visit(db, r.end - timedelta(milliseconds=1), minutes=5)
    await visit(db, r.end, minutes=5)
    await visit(db, r.start - timedelta(milliseconds=1), minutes=5)
    assert_pdf(await pdf(admin, "visits", range="custom", **{"from": "2026-09-10", "to": "2026-09-11"}))
    assert [row[0] for row in pdf_rows] == [last["visit_number"], first["visit_number"]]
    assert pdf_rows[1][10] == "2026-09-10 00:00"                              # Check-in, Karachi time


# ------------------------------------------------------------------------------------------ privacy, text
async def test_pdfs_hold_nothing_private(harness, admin, people, drawn):  # noqa: F811
    await ban(harness, number="35201-7654321-2")
    await lookup(admin, "35201-7654321-2")
    ids = [people["va"]["id"], people["vb"]["id"], people["a"]["id"], people["b"]["id"],
           *(str(u) for u in people["users"].values())]
    for report in REPORTS:
        drawn.clear()
        body = assert_pdf(await pdf(admin, report))
        text = "\n".join(t for _, _, t in drawn)
        for secret in (CNIC, CNIC.replace("-", ""), "35201-7654321-2", "3520176543212", "03001234567",
                       "03217654321", "Laptop", "LEA1234", "photo", "token", "password", "session",
                       "reason_note", "source_audit_id", "metadata", *ids):
            assert secret not in text, (report, secret)
            assert secret.encode() not in body, (report, secret)
    drawn.clear()
    await pdf(admin, "visits")
    texts = {t for _, _, t in drawn}
    assert {"***********67-1", "***********21-2", "*******4567", "*******4321"} <= texts


async def test_urdu_is_shaped_and_right_to_left(harness, admin, drawn):
    await visit(harness.db, datetime.now(UTC) - timedelta(minutes=5), minutes=1, visitor_name="علی خان")
    assert_pdf(await pdf(admin, "visits"))
    urdu = [(method, font) for method, font, t in drawn if t == "علی خان"]
    assert urdu == [("drawRightString", rp.SHAPED)]                          # shaped font, right-aligned
    latin = [font for _, font, t in drawn if t == "Main Gate"]
    assert latin and set(latin) == {rp.BODY}                                 # Latin text: the plain font
    # The shaping itself (what the canvas does with the SHAPED font): HarfBuzz turns the letters into their
    # joined forms (Arabic presentation forms: initial, medial, final) in right-to-left visual order.
    from reportlab.pdfbase.ttfonts import ShapedStr, shapeStr
    shaped = shapeStr("علی خان", rp.SHAPED, 8)
    assert isinstance(shaped, ShapedStr) and len(shaped.__shapeData__) == 7
    joined = [ch for ch in str(shaped) if "ﭐ" <= ch <= "﷿" or "ﹰ" <= ch <= "﻿"]
    assert len(joined) >= 5                                                  # letters in their connected forms
    assert str(shaped)[0] == "ن" and str(shaped)[-1] == "ﻋ"              # right to left: ends with initial ain
    assert not isinstance(shapeStr("Main Gate", rp.SHAPED, 8), ShapedStr)     # Latin text is left as it is


async def test_text_is_drawn_as_it_is_never_as_markup(harness, admin, drawn):
    dep = ObjectId()
    name = "<b>R&D</b> <script>alert(1)</script> =cmd|' /C calc'!A0"
    await harness.db.departments.insert_one({"_id": dep, "name": name, "is_active": True,
                                             "created_at": datetime.now(UTC), "updated_at": datetime.now(UTC)})
    await visit(harness.db, datetime.now(UTC) - timedelta(minutes=5), minutes=1, dep=dep, dep_name=name)
    assert_pdf(await pdf(admin, "departments"))
    joined = "".join(t for _, _, t in drawn).replace(" ", "")                 # the name may wrap at a space
    assert name.replace(" ", "") in joined                                  # every character, literally


# ------------------------------------------------------------------------------------------ formats, size, failures
@pytest.mark.parametrize("fmt,status", [("pdf", 200), ("csv", 200), ("xlsx", 200), ("xls", 422), ("docx", 422),
                                        ("PDF", 422), ("", 422)])
async def test_formats(admin, fmt, status):
    r = await admin.get(f"{BASE}/visits/export", params={"format": fmt})
    assert r.status_code == status, (fmt, r.text[:200] if status != 200 else "")
    if status == 422:
        assert r.json()["error"]["code"] == "validation_error"


async def test_the_row_limit_applies_before_anything_is_drawn(harness, admin, people, monkeypatch, drawn):  # noqa: F811
    monkeypatch.setattr(exports, "EXPORT_MAX_ROWS", 2)
    assert_pdf(await pdf(admin, "visits"))                                   # exactly at the limit: allowed
    monkeypatch.setattr(exports, "EXPORT_MAX_ROWS", 1)
    drawn.clear()
    before = leftover_files()
    r = await pdf(admin, "visits")
    assert (r.status_code, r.json()["error"]["code"]) == (422, "export_too_large")
    assert drawn == [] and leftover_files() <= before                         # no PDF was started
    assert await harness.db.audit_logs.count_documents({"action": "REPORT_EXPORTED", "metadata.format": "pdf"}) == 1


async def test_a_failure_while_drawing_leaves_no_file_and_no_audit(harness, admin, people, monkeypatch):  # noqa: F811
    before = leftover_files()

    def broken(self, batch):
        raise RuntimeError("drawing failed")

    monkeypatch.setattr(rp.PdfTable, "add_rows", broken)
    r = await pdf(admin, "visits")
    assert r.status_code == 500 and r.headers["content-type"].startswith("application/json")
    assert "drawing failed" not in r.text
    assert leftover_files() <= before
    assert await harness.db.audit_logs.count_documents({"action": "REPORT_EXPORTED"}) == 0


async def test_without_a_unicode_font_pdf_is_refused_and_other_formats_still_work(harness, admin, people, monkeypatch,  # noqa: F811
                                                                                  tmp_path):
    monkeypatch.setattr(rp, "_registered", False)
    monkeypatch.setattr(rp, "fonts_folder", lambda: tmp_path)                # a server without the fonts
    before = leftover_files()
    r = await pdf(admin, "visits")
    assert (r.status_code, r.json()["error"]["code"]) == (503, "pdf_unavailable")
    assert leftover_files() <= before
    assert await harness.db.audit_logs.count_documents({"action": "REPORT_EXPORTED"}) == 0
    assert (await admin.get(f"{BASE}/visits/export", params={"format": "csv"})).status_code == 200
    assert (await admin.get(f"{BASE}/visits/export", params={"format": "xlsx"})).status_code == 200


async def test_exports_are_audited_as_pdf(harness, admin, people):  # noqa: F811
    await pdf(admin, "visits", q="alia", range="this_week")
    [entry] = await harness.db.audit_logs.find({"action": "REPORT_EXPORTED"}).to_list(length=5)
    assert (entry["metadata"]["format"], entry["metadata"]["rows"], entry["metadata"]["filters"]) == ("pdf", 1, ["q"])
    assert "alia" not in str(entry).lower()
