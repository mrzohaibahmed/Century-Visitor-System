"""
Report exports (CSV and XLSX). Administrators only: the routes require reports:view and reports:export.
Both formats are written from the same columns and the same rows (see xlsx_file for the workbook).

Same data as the report screens, never a second implementation: every export reads its rows from the
same service function and the same row schema as the JSON report (so the same filters, date range,
masking and sort), page by page along the report's own keyset cursor, and writes them as CSV while they
stream out. Memory holds one page at a time. Host, department and guard lists are directory-sized and
already computed whole by their report; their exports contain every row (no screen limit).

Nothing is ever cut short silently: before anything is sent the rows are counted, and an export over
EXPORT_MAX_ROWS is refused ("export_too_large": narrow the range) instead of truncated.

The file:
- UTF-8 with a byte order mark (so spreadsheet programs show Urdu and other scripts correctly), a header
  row, a fixed column order, standard quoting (csv module: commas, quotes and line breaks are safe);
- only the columns listed here: ID numbers and phones masked (as in the reports), no internal ids, no
  photo, pass, belongings, notes, account or audit data;
- times as ISO 8601 in the organisation's time zone (e.g. 2026-09-30T14:05:00+05:00);
- formula injection: a text cell starting with = + - @, a tab or a carriage return gets a leading
  apostrophe, the usual (OWASP) mitigation, so a spreadsheet shows it as text and never runs it.
"""
import asyncio
import contextlib
import csv
import io
import os
import tempfile
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from pymongo.asynchronous.database import AsyncDatabase

from app.core.errors import AppError
from app.core.timeutil import DayRange
from app.schemas.reports import DenialRow, VisitorSummaryRow, VisitReportRow, VisitReportSort
from app.services import reports
from app.services.visits import VisitFilter

EXPORT_MAX_ROWS = 100_000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
BOM = "﻿"


def export_too_large(rows: int) -> AppError:
    return AppError(422, "export_too_large",
                    f"This export would have {rows:,} rows; at most {EXPORT_MAX_ROWS:,} can be exported at once. "
                    "Choose a shorter date range or more filters.")


def check_size(rows: int) -> None:
    if rows > EXPORT_MAX_ROWS:
        raise export_too_large(rows)


def cell(value, tz: ZoneInfo) -> str | int:
    """One CSV cell: numbers stay numbers; text that a spreadsheet would treat as a formula is prefixed."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return value
    if isinstance(value, datetime):
        return value.astimezone(tz).isoformat()
    text = str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


@dataclass(frozen=True)
class Column:
    header: str
    value: Callable[[object], object]


def _name(ref) -> str | None:
    return ref.name if ref else None


# The columns of each export: the report's approved fields, in this order.
VISIT_COLUMNS = [
    Column("Visit number", lambda r: r.visit_number),
    Column("Visitor", lambda r: r.visitor.name),
    Column("ID type", lambda r: r.id_type),
    Column("ID number (masked)", lambda r: r.id_number),
    Column("Phone (masked)", lambda r: r.phone),
    Column("Host", lambda r: r.host.name),
    Column("Host not listed", lambda r: r.host_unlisted),
    Column("Department", lambda r: r.department.name),
    Column("Purpose", lambda r: r.reason_code),
    Column("Gate", lambda r: r.gate.name),
    Column("Check-in", lambda r: r.check_in_at),
    Column("Check-out", lambda r: r.check_out_at),
    Column("Duration (minutes)", lambda r: r.duration_minutes),
    Column("Status", lambda r: r.status),
    Column("Checked in by", lambda r: r.checked_in_by.name),
    Column("Checked out by", lambda r: _name(r.checked_out_by)),
]
INSIDE_COLUMNS = [
    Column("Visit number", lambda r: r.visit_number),
    Column("Visitor", lambda r: r.visitor.name),
    Column("ID type", lambda r: r.id_type),
    Column("ID number (masked)", lambda r: r.id_number),
    Column("Phone (masked)", lambda r: r.phone),
    Column("Host", lambda r: r.host.name),
    Column("Department", lambda r: r.department.name),
    Column("Gate", lambda r: r.gate.name),
    Column("Check-in", lambda r: r.check_in_at),
    Column("Inside for (minutes)", lambda r: r.duration_minutes),
    Column("Checked in by", lambda r: r.checked_in_by.name),
]
VISITOR_COLUMNS = [
    Column("Visitor", lambda r: r.visitor.name),
    Column("ID type", lambda r: r.id_type),
    Column("ID number (masked)", lambda r: r.id_number),
    Column("Phone (masked)", lambda r: r.phone),
    Column("Visits", lambda r: r.visits),
    Column("Completed visits", lambda r: r.completed_visits),
    Column("First visit", lambda r: r.first_visit_at),
    Column("Last visit", lambda r: r.last_visit_at),
    Column("Average duration (minutes)", lambda r: r.avg_duration_minutes),
    Column("Inside now", lambda r: r.inside_now),
]
HOST_COLUMNS = [
    Column("Host", lambda r: r["host"]["name"]),
    Column("Host not listed", lambda r: r["host_unlisted"]),
    Column("Department", lambda r: r["department"]["name"]),
    Column("Visits", lambda r: r["visits"]),
    Column("Completed visits", lambda r: r["completed_visits"]),
    Column("Inside now", lambda r: r["inside_now"]),
]
DEPARTMENT_COLUMNS = [
    Column("Department", lambda r: r["department"]["name"]),
    Column("Visits", lambda r: r["visits"]),
    Column("Completed visits", lambda r: r["completed_visits"]),
    Column("Unique visitors", lambda r: r["unique_visitors"]),
    Column("Average duration (minutes)", lambda r: r["avg_duration_minutes"]),
    Column("Inside now", lambda r: r["inside_now"]),
]
GUARD_COLUMNS = [
    Column("Operator", lambda r: r["guard"]["name"]),
    Column("Role", lambda r: r["guard"]["role"]),
    Column("Active", lambda r: r["guard"]["is_active"]),
    Column("Check-ins", lambda r: r["check_ins"]),
    Column("Check-outs", lambda r: r["check_outs"]),
    Column("Inside now", lambda r: r["inside_now"]),
    Column("Denied entries", lambda r: r["denied_entries"]),
    Column("Watchlist matches", lambda r: r["watchlist_matches"]),
]
DENIAL_COLUMNS = [
    Column("Time", lambda r: r.at),
    Column("Source", lambda r: r.source),
    Column("Reason", lambda r: r.reason),
    Column("Purpose", lambda r: r.reason_code),
    Column("Visitor", lambda r: r.visitor.name),
    Column("ID (masked)", lambda r: r.identifier),
    Column("Watchlist reason", lambda r: r.watchlist.reason),
    Column("Gate", lambda r: r.gate.name),
    Column("Operator", lambda r: r.operator.name),
    Column("Names from current records", lambda r: ", ".join(r.current_names)),
]


# ------------------------------------------------------------------------------------------ rows
async def visit_rows(db: AsyncDatabase, f: VisitFilter, sort: VisitReportSort, *,
                     bounded: bool = True) -> AsyncIterator[VisitReportRow]:
    """Every row of the visit report (or, bounded=False, of the currently-inside report), page by page."""
    cursor = None
    while True:
        docs, cursor, _, as_of = await reports.visit_report(db, f, sort=sort, cursor=cursor,
                                                            limit=reports.PAGE_LIMIT_MAX, bounded=bounded,
                                                            count=False)
        people = await reports.visitor_identities(db, [d["visitor_id"] for d in docs])
        for d in docs:
            yield VisitReportRow.from_doc(d, people.get(d["visitor_id"]), as_of)
        if not cursor:
            return


async def visitor_rows(db: AsyncDatabase, f: VisitFilter, sort: str) -> AsyncIterator[VisitorSummaryRow]:
    cursor = None
    while True:
        groups, cursor, _, people, inside = await reports.visitor_summary(
            db, f, sort=sort, cursor=cursor, limit=reports.PAGE_LIMIT_MAX, count=False)
        for g in groups:
            yield VisitorSummaryRow.from_group(g, people.get(g["_id"]), g["_id"] in inside)
        if not cursor:
            return


async def denial_rows(db: AsyncDatabase, r: DayRange, **filters) -> AsyncIterator[DenialRow]:
    cursor = None
    while True:
        rows, cursor, _ = await reports.denial_report(db, r, cursor=cursor, limit=reports.PAGE_LIMIT_MAX,
                                                      count=False, **filters)
        for row in rows:
            yield DenialRow(**row)
        if not cursor:
            return


async def _as_async(rows: Iterable) -> AsyncIterator:
    for row in rows:
        yield row


def listed(rows: Iterable) -> AsyncIterator:
    """An already-computed (directory-sized) list, as rows to stream."""
    return _as_async(rows)


# ------------------------------------------------------------------------------------------ CSV
async def csv_stream(columns: list[Column], rows: AsyncIterator, tz_name: str,
                     chunk_rows: int = 200) -> AsyncIterator[bytes]:
    """The CSV file, a chunk at a time: the header first, then the rows as they come."""
    tz = ZoneInfo(tz_name)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([c.header for c in columns])
    pending = 0
    first = True
    async for row in rows:
        writer.writerow([cell(c.value(row), tz) for c in columns])
        pending += 1
        if pending >= chunk_rows:
            yield ((BOM if first else "") + buffer.getvalue()).encode("utf-8")
            first, pending = False, 0
            buffer.seek(0)
            buffer.truncate()
    yield ((BOM if first else "") + buffer.getvalue()).encode("utf-8")


# ------------------------------------------------------------------------------------------ XLSX
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_XLSX_DATETIME = "yyyy-mm-dd hh:mm"
SHEET_TITLES = {"visits": "Visits", "visitors": "Visitors", "hosts": "Hosts", "departments": "Departments",
                "guards": "Guards", "inside": "Currently inside", "denials": "Refused entries"}


async def xlsx_file(columns: list[Column], rows: AsyncIterator, *, report: str, tz_name: str,
                    about: list[tuple[str, str]]) -> str:
    """Builds the workbook in a temporary file (returned; the caller deletes it once sent) from the SAME
    columns and rows as the CSV. Sheet 1: the report (bold frozen header, filter buttons, numbers as
    numbers, date-times in the organisation's time zone). Sheet 2 "About": what the file contains.

    Memory stays flat: constant_memory writes each finished row to disk. Every text cell is written as
    text (never parsed as a formula, a number or a link), so formula injection is impossible without
    changing any value. Anything that fails removes the file; nothing half-built is ever sent."""
    import xlsxwriter  # only needed for this format

    tz = ZoneInfo(tz_name)
    handle, path = tempfile.mkstemp(prefix="cgvms-report-", suffix=".xlsx")
    os.close(handle)
    try:
        book = xlsxwriter.Workbook(path, {"constant_memory": True, "strings_to_formulas": False,
                                          "strings_to_numbers": False, "strings_to_urls": False})
        bold = book.add_format({"bold": True})
        when = book.add_format({"num_format": _XLSX_DATETIME})
        sheet = book.add_worksheet(SHEET_TITLES.get(report, "Report"))
        for i, column in enumerate(columns):
            sheet.set_column(i, i, max(12, min(40, len(column.header) + 4)))
        sheet.write_row(0, 0, [c.header for c in columns], bold)
        last = 0
        async for row in rows:
            last += 1
            for i, column in enumerate(columns):
                value = column.value(row)
                if value is None:
                    continue
                if isinstance(value, bool):
                    sheet.write_string(last, i, "Yes" if value else "No")
                elif isinstance(value, int):
                    sheet.write_number(last, i, value)
                elif isinstance(value, datetime):          # Excel has no time zones: local wall-clock time
                    sheet.write_datetime(last, i, value.astimezone(tz).replace(tzinfo=None), when)
                else:
                    sheet.write_string(last, i, str(value))
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, last, len(columns) - 1)

        info = book.add_worksheet("About")
        info.set_column(0, 0, 22)
        info.set_column(1, 1, 60)
        for n, (label, text) in enumerate(about):
            info.write_string(n, 0, label, bold)
            info.write_string(n, 1, text)
        await asyncio.to_thread(book.close)               # zipping is CPU work: off the event loop
        return path
    except BaseException:
        discard(path)
        raise


def discard(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)


def filename(report: str, r: DayRange | None = None, at: datetime | None = None, tz_name: str | None = None) -> str:
    """Built only from the report's fixed name and server-resolved dates, never from request text."""
    if r is not None:
        days = r.first_day.isoformat() if r.days == 1 else f"{r.first_day.isoformat()}_to_{r.last_day.isoformat()}"
        return f"century-gate-{report}-{days}.csv"
    local = at.astimezone(ZoneInfo(tz_name)) if at and tz_name else at
    return f"century-gate-{report}-{local:%Y-%m-%d-%H%M}.csv"
