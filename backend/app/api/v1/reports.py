"""Reports (administrators only: reports:view). Guards are refused (and the attempt audited) by require().

Each report's query parameters are parsed by ONE dependency, shared by its JSON route and its CSV export
(`.../export`), so a filter can never mean something different in the file than on the screen. Exports
also require reports:export, are audited (report, range, filter names, row count; never values), and
stream as CSV (see services/report_exports)."""
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pymongo.asynchronous.database import AsyncDatabase

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.permissions import Permission
from app.core.timeutil import DayRange, RangePreset
from app.db.client import Database
from app.schemas.common import IdStr
from app.schemas.reports import (
    DenialPage,
    DenialSource,
    DepartmentPage,
    GuardPage,
    HostPage,
    InsidePage,
    InsideSort,
    OverviewOut,
    ReportRangeOut,
    VisitorSummaryPage,
    VisitorSummaryRow,
    VisitorSummarySort,
    VisitReportPage,
    VisitReportRow,
    VisitReportSort,
)
from app.schemas.visits import VisitReason, VisitStatus
from app.services import audit
from app.services import report_exports as exports
from app.services import reports as svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext
from app.services.visits import VisitFilter, object_id

router = APIRouter(prefix="/reports", tags=["reports"])
view = require(Permission.REPORTS_VIEW)
EXPORT = [Depends(require(Permission.REPORTS_EXPORT))]      # in addition to reports:view


class ExportFormat(StrEnum):
    CSV = "csv"                      # XLSX and PDF: later steps


def _oid(value: str | None):
    return object_id(value) if value else None          # already validated by IdStr


# ------------------------------------------------------------------------------------------ shared parameters
def report_range(preset: RangePreset = Query(default=RangePreset.TODAY, alias="range"),
                 date_from: date | None = Query(default=None, alias="from"),
                 date_to: date | None = Query(default=None, alias="to"),
                 settings: Settings = Depends(get_settings)) -> DayRange:
    return svc.report_range(settings, preset, date_from, date_to)


@dataclass(frozen=True)
class VisitParams:
    range: DayRange
    filter: VisitFilter
    sort: VisitReportSort


def visit_params(r: DayRange = Depends(report_range), q: str | None = Query(default=None, max_length=100),
                 status: VisitStatus | None = None,
                 host_id: IdStr | None = None, department_id: IdStr | None = None, gate_id: IdStr | None = None,
                 guard_id: IdStr | None = None, reason_code: VisitReason | None = None,
                 sort: VisitReportSort = VisitReportSort.CHECK_IN_DESC) -> VisitParams:
    return VisitParams(r, VisitFilter(start=r.start, end=r.end, status=status, host_id=_oid(host_id),
                                      department_id=_oid(department_id), gate_id=_oid(gate_id),
                                      guard_id=_oid(guard_id), reason_code=reason_code, q=q), sort)


@dataclass(frozen=True)
class VisitorParams:
    range: DayRange
    filter: VisitFilter
    sort: VisitorSummarySort


def visitor_params(r: DayRange = Depends(report_range), q: str | None = Query(default=None, max_length=100),
                   host_id: IdStr | None = None, department_id: IdStr | None = None, gate_id: IdStr | None = None,
                   sort: VisitorSummarySort = VisitorSummarySort.LAST_VISIT_DESC) -> VisitorParams:
    return VisitorParams(r, VisitFilter(start=r.start, end=r.end, host_id=_oid(host_id),
                                        department_id=_oid(department_id), gate_id=_oid(gate_id), q=q), sort)


@dataclass(frozen=True)
class InsideParams:
    filter: VisitFilter
    sort: VisitReportSort


def inside_params(q: str | None = Query(default=None, max_length=100),
                  host_id: IdStr | None = None, department_id: IdStr | None = None, gate_id: IdStr | None = None,
                  sort: InsideSort = InsideSort.CHECK_IN_ASC) -> InsideParams:
    """No date range: the current state."""
    return InsideParams(VisitFilter(status="CHECKED_IN", host_id=_oid(host_id), department_id=_oid(department_id),
                                    gate_id=_oid(gate_id), q=q), VisitReportSort(str(sort)))


@dataclass(frozen=True)
class DenialParams:
    range: DayRange
    source: str | None
    operator_id: object
    gate_id: object

    def filters(self) -> dict:
        return {"source": self.source, "operator_id": self.operator_id, "gate_id": self.gate_id}


def denial_params(r: DayRange = Depends(report_range), source: DenialSource | None = None,
                  guard_id: IdStr | None = None, gate_id: IdStr | None = None) -> DenialParams:
    return DenialParams(r, str(source) if source else None, _oid(guard_id), _oid(gate_id))


@dataclass(frozen=True)
class HostParams:
    range: DayRange
    department_id: object


def host_params(r: DayRange = Depends(report_range), department_id: IdStr | None = None) -> HostParams:
    return HostParams(r, _oid(department_id))


# ------------------------------------------------------------------------------------------ JSON reports
@router.get("/overview", response_model=OverviewOut, response_model_by_alias=True)
async def report_overview(ctx: AuthContext = Depends(view), r: DayRange = Depends(report_range),
                          database: Database = Depends(get_database)) -> OverviewOut:
    """Cards and chart series for the visits that checked in within the range (Asia/Karachi days).
    `totals.inside_now` is the current state and does not depend on the range."""
    return OverviewOut(range=ReportRangeOut.from_range(r), **await svc.overview(database.db, r))


@router.get("/visits", response_model=VisitReportPage, response_model_by_alias=True)
async def report_visits(ctx: AuthContext = Depends(view), p: VisitParams = Depends(visit_params),
                        cursor: str | None = Query(default=None, max_length=1000),
                        limit: int = Query(default=25, ge=1, le=100),
                        database: Database = Depends(get_database)) -> VisitReportPage:
    """The visit report: filters as in the visit history plus guard (checked in OR out) and purpose.
    ID numbers and phone numbers are always masked."""
    docs, next_cursor, total, as_of = await svc.visit_report(database.db, p.filter, sort=p.sort, cursor=cursor,
                                                             limit=limit)
    people = await svc.visitor_identities(database.db, [d["visitor_id"] for d in docs])
    return VisitReportPage(range=ReportRangeOut.from_range(p.range), total=total, next_cursor=next_cursor,
                           items=[VisitReportRow.from_doc(d, people.get(d["visitor_id"]), as_of) for d in docs])


@router.get("/visitors", response_model=VisitorSummaryPage, response_model_by_alias=True)
async def report_visitors(ctx: AuthContext = Depends(view), p: VisitorParams = Depends(visitor_params),
                          cursor: str | None = Query(default=None, max_length=1000),
                          limit: int = Query(default=25, ge=1, le=100),
                          database: Database = Depends(get_database)) -> VisitorSummaryPage:
    """Per visitor: their visits that checked in within the range (and match the filters): counts, first and
    last visit, average completed stay. `inside_now` is the current state. ID and phone always masked."""
    groups, next_cursor, total, people, inside = await svc.visitor_summary(
        database.db, p.filter, sort=str(p.sort), cursor=cursor, limit=limit)
    return VisitorSummaryPage(
        range=ReportRangeOut.from_range(p.range), total=total, next_cursor=next_cursor,
        items=[VisitorSummaryRow.from_group(g, people.get(g["_id"]), g["_id"] in inside) for g in groups])


@router.get("/hosts", response_model=HostPage, response_model_by_alias=True)
async def report_hosts(ctx: AuthContext = Depends(view), p: HostParams = Depends(host_params),
                       limit: int = Query(default=100, ge=1, le=svc.GROUP_LIMIT_MAX),
                       database: Database = Depends(get_database)) -> HostPage:
    """Visits per host (and department) within the range, most visited first. `inside_now`: current state."""
    rows, total, truncated = await svc.host_report(database.db, p.range, department_id=p.department_id, limit=limit)
    return HostPage(range=ReportRangeOut.from_range(p.range), items=rows, total=total, truncated=truncated)


@router.get("/departments", response_model=DepartmentPage, response_model_by_alias=True)
async def report_departments(ctx: AuthContext = Depends(view), r: DayRange = Depends(report_range),
                             limit: int = Query(default=100, ge=1, le=svc.GROUP_LIMIT_MAX),
                             database: Database = Depends(get_database)) -> DepartmentPage:
    """Visits per department within the range, most visited first. `inside_now`: current state."""
    rows, total, truncated = await svc.department_report(database.db, r, limit=limit)
    return DepartmentPage(range=ReportRangeOut.from_range(r), items=rows, total=total, truncated=truncated)


@router.get("/guards", response_model=GuardPage, response_model_by_alias=True)
async def report_guards(ctx: AuthContext = Depends(view), r: DayRange = Depends(report_range),
                        limit: int = Query(default=100, ge=1, le=svc.GROUP_LIMIT_MAX),
                        database: Database = Depends(get_database)) -> GuardPage:
    """What each operator handled within the range, from the operator recorded with each check-in,
    check-out and refusal. `inside_now`: current state."""
    rows, total, truncated = await svc.guard_report(database.db, r, limit=limit)
    return GuardPage(range=ReportRangeOut.from_range(r), items=rows, total=total, truncated=truncated)


@router.get("/inside", response_model=InsidePage)
async def report_inside(ctx: AuthContext = Depends(view), p: InsideParams = Depends(inside_params),
                        cursor: str | None = Query(default=None, max_length=1000),
                        limit: int = Query(default=25, ge=1, le=100),
                        database: Database = Depends(get_database)) -> InsidePage:
    """Everyone inside right now (the current state: no date range), longest inside first by default.
    Check-out stays in the existing check-out workflow. ID and phone always masked."""
    docs, next_cursor, total, as_of = await svc.visit_report(
        database.db, p.filter, sort=p.sort, cursor=cursor, limit=limit, bounded=False)
    people = await svc.visitor_identities(database.db, [d["visitor_id"] for d in docs])
    return InsidePage(generated_at=as_of, total=total, next_cursor=next_cursor,
                      items=[VisitReportRow.from_doc(d, people.get(d["visitor_id"]), as_of) for d in docs])


@router.get("/denials", response_model=DenialPage, response_model_by_alias=True)
async def report_denials(ctx: AuthContext = Depends(view), p: DenialParams = Depends(denial_params),
                         cursor: str | None = Query(default=None, max_length=1000),
                         limit: int = Query(default=25, ge=1, le=100),
                         database: Database = Depends(get_database)) -> DenialPage:
    """Refused entries within the range (entry_denials), newest first. `denied_entries` and
    `watchlist_matches` cover the whole range, exactly as in the overview; `total` follows the filters."""
    counts = await svc.security_counts(database.db, p.range.start, p.range.end)
    rows, next_cursor, total = await svc.denial_report(database.db, p.range, cursor=cursor, limit=limit,
                                                       **p.filters())
    return DenialPage(range=ReportRangeOut.from_range(p.range), denied_entries=counts.denied_entries,
                      watchlist_matches=counts.watchlist_matches, total=total, next_cursor=next_cursor, items=rows)


# ------------------------------------------------------------------------------------------ CSV exports
def _used(**values) -> list[str]:
    """The names of the filters in use (never their values: a search may be an ID number)."""
    return sorted(name for name, value in values.items() if value)


async def _export(db: AsyncDatabase, request: Request, ctx: AuthContext, *, report: str, fmt: ExportFormat,
                  columns: list, rows, rows_count: int, filters: list[str], name: str, tz_name: str,
                  r: DayRange | None = None) -> StreamingResponse:
    """Audits the export, then streams it. Everything that can fail with a clear message (filters, range,
    size) has already been checked, so a started download is a complete file."""
    exports.check_size(rows_count)
    await audit.record(db, AuditAction.REPORT_EXPORTED, actor=actor_from_user(ctx.user), ip=request_meta(request).ip,
                       resource_type="report", metadata={
                           "report": report, "format": str(fmt), "rows": rows_count, "filters": filters,
                           "range": {"preset": str(r.preset), "from": r.first_day.isoformat(),
                                     "to": r.last_day.isoformat()} if r else None})
    return StreamingResponse(exports.csv_stream(columns, rows, tz_name), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{name}"',
                                      "Cache-Control": "no-store, private"})


@router.get("/visits/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_visits(request: Request, ctx: AuthContext = Depends(view), p: VisitParams = Depends(visit_params),
                        format: ExportFormat = ExportFormat.CSV, database: Database = Depends(get_database),
                        settings: Settings = Depends(get_settings)) -> StreamingResponse:
    """The visit report as a file: same filters, sort, masking and columns as the screen (no internal ids)."""
    f = p.filter
    total = await svc.count_visits(database.db, f)
    return await _export(database.db, request, ctx, report="visits", fmt=format, columns=exports.VISIT_COLUMNS,
                         rows=exports.visit_rows(database.db, f, p.sort), rows_count=total, r=p.range,
                         filters=_used(q=f.q, status=f.status, host=f.host_id, department=f.department_id,
                                       gate=f.gate_id, guard=f.guard_id, reason_code=f.reason_code),
                         name=exports.filename("visits", p.range), tz_name=settings.timezone)


@router.get("/visitors/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_visitors(request: Request, ctx: AuthContext = Depends(view),
                          p: VisitorParams = Depends(visitor_params), format: ExportFormat = ExportFormat.CSV,
                          database: Database = Depends(get_database),
                          settings: Settings = Depends(get_settings)) -> StreamingResponse:
    f = p.filter
    total = await svc.count_visitors(database.db, f)
    return await _export(database.db, request, ctx, report="visitors", fmt=format, columns=exports.VISITOR_COLUMNS,
                         rows=exports.visitor_rows(database.db, f, str(p.sort)), rows_count=total, r=p.range,
                         filters=_used(q=f.q, host=f.host_id, department=f.department_id, gate=f.gate_id),
                         name=exports.filename("visitors", p.range), tz_name=settings.timezone)


@router.get("/hosts/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_hosts(request: Request, ctx: AuthContext = Depends(view), p: HostParams = Depends(host_params),
                       format: ExportFormat = ExportFormat.CSV, database: Database = Depends(get_database),
                       settings: Settings = Depends(get_settings)) -> StreamingResponse:
    rows, total, _ = await svc.host_report(database.db, p.range, department_id=p.department_id, limit=None)
    return await _export(database.db, request, ctx, report="hosts", fmt=format, columns=exports.HOST_COLUMNS,
                         rows=exports.listed(rows), rows_count=total, r=p.range,
                         filters=_used(department=p.department_id),
                         name=exports.filename("hosts", p.range), tz_name=settings.timezone)


@router.get("/departments/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_departments(request: Request, ctx: AuthContext = Depends(view), r: DayRange = Depends(report_range),
                             format: ExportFormat = ExportFormat.CSV, database: Database = Depends(get_database),
                             settings: Settings = Depends(get_settings)) -> StreamingResponse:
    rows, total, _ = await svc.department_report(database.db, r, limit=None)
    return await _export(database.db, request, ctx, report="departments", fmt=format,
                         columns=exports.DEPARTMENT_COLUMNS, rows=exports.listed(rows), rows_count=total, r=r,
                         filters=[], name=exports.filename("departments", r), tz_name=settings.timezone)


@router.get("/guards/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_guards(request: Request, ctx: AuthContext = Depends(view), r: DayRange = Depends(report_range),
                        format: ExportFormat = ExportFormat.CSV, database: Database = Depends(get_database),
                        settings: Settings = Depends(get_settings)) -> StreamingResponse:
    rows, total, _ = await svc.guard_report(database.db, r, limit=None)
    return await _export(database.db, request, ctx, report="guards", fmt=format, columns=exports.GUARD_COLUMNS,
                         rows=exports.listed(rows), rows_count=total, r=r, filters=[],
                         name=exports.filename("guards", r), tz_name=settings.timezone)


@router.get("/inside/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_inside(request: Request, ctx: AuthContext = Depends(view), p: InsideParams = Depends(inside_params),
                        format: ExportFormat = ExportFormat.CSV, database: Database = Depends(get_database),
                        settings: Settings = Depends(get_settings)) -> StreamingResponse:
    """Everyone inside right now (current state; no date range)."""
    f = p.filter
    total = await svc.count_visits(database.db, f)
    return await _export(database.db, request, ctx, report="inside", fmt=format, columns=exports.INSIDE_COLUMNS,
                         rows=exports.visit_rows(database.db, f, p.sort, bounded=False), rows_count=total,
                         filters=_used(q=f.q, host=f.host_id, department=f.department_id, gate=f.gate_id),
                         name=exports.filename("inside", at=datetime.now(UTC), tz_name=settings.timezone),
                         tz_name=settings.timezone)


@router.get("/denials/export", dependencies=EXPORT, response_class=StreamingResponse)
async def export_denials(request: Request, ctx: AuthContext = Depends(view), p: DenialParams = Depends(denial_params),
                         format: ExportFormat = ExportFormat.CSV, database: Database = Depends(get_database),
                         settings: Settings = Depends(get_settings)) -> StreamingResponse:
    """Refused entries (entry_denials only; never rebuilt from the audit trail)."""
    total = await svc.count_denials(database.db, p.range, **p.filters())
    return await _export(database.db, request, ctx, report="denials", fmt=format, columns=exports.DENIAL_COLUMNS,
                         rows=exports.denial_rows(database.db, p.range, **p.filters()), rows_count=total, r=p.range,
                         filters=_used(source=p.source, guard=p.operator_id, gate=p.gate_id),
                         name=exports.filename("denials", p.range), tz_name=settings.timezone)
