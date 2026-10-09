"""Visits: check-in, check-out, active list, history."""
from datetime import date

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.common import Page
from app.schemas.visits import (
    ActiveVisits,
    CheckInRequest,
    CheckOutLookup,
    CheckOutResult,
    UpdateBelongingsRequest,
    VisitOut,
    VisitStatus,
)
from app.services import visits as svc
from app.services.auth import AuthContext

router = APIRouter(prefix="/visits", tags=["visits"])


@router.post("", response_model=VisitOut, status_code=201)
async def check_in(body: CheckInRequest, request: Request,
                   ctx: AuthContext = Depends(require(Permission.VISIT_CHECK_IN)),
                   database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> VisitOut:
    visit = await svc.check_in(database.db, settings, ctx, request_meta(request), body)
    worker = getattr(request.app.state, "email_worker", None)
    if worker is not None:
        worker.wake()                  # send the host's and department's e-mails now; the check-in does not wait for it
    return VisitOut.from_doc(visit)


@router.get("/active", response_model=ActiveVisits)
async def active_visits(ctx: AuthContext = Depends(require(Permission.VISIT_READ)),
                        database: Database = Depends(get_database)) -> ActiveVisits:
    docs, total = await svc.list_active(database.db)
    return ActiveVisits(items=[VisitOut.from_doc(d) for d in docs], total=total)


@router.get("", response_model=Page[VisitOut])
async def list_visits(
    status: VisitStatus | None = None,
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    host_id: str | None = None, department_id: str | None = None, gate_id: str | None = None,
    q: str | None = Query(default=None, max_length=100), cursor: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    ctx: AuthContext = Depends(require(Permission.VISIT_READ)),
    database: Database = Depends(get_database), settings: Settings = Depends(get_settings),
) -> Page[VisitOut]:
    docs, next_cursor = await svc.list_visits(
        database.db, settings, status=status, day_from=date_from, day_to=date_to, host_id=host_id,
        department_id=department_id, gate_id=gate_id, visitor_id=None, q=q, cursor=cursor, limit=limit)
    return Page[VisitOut](items=[VisitOut.from_doc(d) for d in docs], next_cursor=next_cursor)


@router.post("/check-out", response_model=CheckOutResult)
async def check_out_by_lookup(body: CheckOutLookup, request: Request,
                              ctx: AuthContext = Depends(require(Permission.VISIT_CHECK_OUT)),
                              database: Database = Depends(get_database)) -> CheckOutResult:
    """Check-out by typed or scanned value (visit number or the visitor's ID number)."""
    visit, already = await svc.resolve_and_check_out(
        database.db, ctx, request_meta(request), visit_number=body.visit_number,
        identity=body.identity.model_dump(mode="json") if body.identity else None)
    return CheckOutResult(visit=VisitOut.from_doc(visit), already_checked_out=already)


@router.get("/{visit_id}", response_model=VisitOut)
async def get_visit(visit_id: str, ctx: AuthContext = Depends(require(Permission.VISIT_READ)),
                    database: Database = Depends(get_database)) -> VisitOut:
    return VisitOut.from_doc(await svc.get_visit(database.db, visit_id))


@router.patch("/{visit_id}/belongings", response_model=VisitOut)
async def update_belongings(visit_id: str, body: UpdateBelongingsRequest, request: Request,
                            ctx: AuthContext = Depends(require(Permission.VISIT_CHECK_IN)),
                            database: Database = Depends(get_database)) -> VisitOut:
    """Update personal material on an active visit (same slip used at check-in)."""
    visit = await svc.update_belongings(database.db, ctx, request_meta(request), visit_id, body)
    return VisitOut.from_doc(visit)


@router.post("/{visit_id}/check-out", response_model=CheckOutResult)
async def check_out(visit_id: str, request: Request,
                    ctx: AuthContext = Depends(require(Permission.VISIT_CHECK_OUT)),
                    database: Database = Depends(get_database)) -> CheckOutResult:
    visit, already = await svc.check_out(database.db, ctx, request_meta(request), visit_id)
    return CheckOutResult(visit=VisitOut.from_doc(visit), already_checked_out=already)
