"""Reports (administrators only: reports:view). Guards are refused (and the attempt audited) by require()."""
from datetime import date

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_database, get_settings, require
from app.core.config import Settings
from app.core.permissions import Permission
from app.core.timeutil import RangePreset
from app.db.client import Database
from app.schemas.common import IdStr
from app.schemas.reports import OverviewOut, ReportRangeOut, VisitReportPage, VisitReportRow, VisitReportSort
from app.schemas.visits import VisitReason, VisitStatus
from app.services import reports as svc
from app.services.auth import AuthContext
from app.services.visits import VisitFilter, object_id

router = APIRouter(prefix="/reports", tags=["reports"])
view = require(Permission.REPORTS_VIEW)


@router.get("/overview", response_model=OverviewOut, response_model_by_alias=True)
async def report_overview(
    ctx: AuthContext = Depends(view),
    preset: RangePreset = Query(default=RangePreset.TODAY, alias="range"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    database: Database = Depends(get_database), settings: Settings = Depends(get_settings),
) -> OverviewOut:
    """Cards and chart series for the visits that checked in within the range (Asia/Karachi days).
    `totals.inside_now` is the current state and does not depend on the range."""
    r = svc.report_range(settings, preset, date_from, date_to)
    return OverviewOut(range=ReportRangeOut.from_range(r), **await svc.overview(database.db, r))


@router.get("/visits", response_model=VisitReportPage, response_model_by_alias=True)
async def report_visits(
    ctx: AuthContext = Depends(view),
    preset: RangePreset = Query(default=RangePreset.TODAY, alias="range"),
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    q: str | None = Query(default=None, max_length=100),
    status: VisitStatus | None = None,
    host_id: IdStr | None = None, department_id: IdStr | None = None, gate_id: IdStr | None = None,
    guard_id: IdStr | None = None, reason_code: VisitReason | None = None,
    sort: VisitReportSort = VisitReportSort.CHECK_IN_DESC,
    cursor: str | None = Query(default=None, max_length=1000),
    limit: int = Query(default=25, ge=1, le=100),
    database: Database = Depends(get_database), settings: Settings = Depends(get_settings),
) -> VisitReportPage:
    """The visit report: filters as in the visit history plus guard (checked in OR out) and purpose.
    ID numbers and phone numbers are always masked."""
    r = svc.report_range(settings, preset, date_from, date_to)

    def oid(value: str | None):
        return object_id(value) if value else None      # already validated by IdStr

    f = VisitFilter(start=r.start, end=r.end, status=status, host_id=oid(host_id), department_id=oid(department_id),
                    gate_id=oid(gate_id), guard_id=oid(guard_id), reason_code=reason_code, q=q)
    docs, next_cursor, total, as_of = await svc.visit_report(database.db, f, sort=sort, cursor=cursor, limit=limit)
    people = await svc.visitor_identities(database.db, [d["visitor_id"] for d in docs])
    return VisitReportPage(range=ReportRangeOut.from_range(r), total=total, next_cursor=next_cursor,
                           items=[VisitReportRow.from_doc(d, people.get(d["visitor_id"]), as_of) for d in docs])
