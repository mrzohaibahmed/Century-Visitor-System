"""Visitor passes (QR on the badge): issue, reissue, revoke, print record, scan and QR check-out."""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.passes import BadgeOut, IssuedPassOut, ScannedPass, ScanOut
from app.schemas.visits import CheckOutResult, VisitOut
from app.services import passes as svc
from app.services.auth import AuthContext

visit_passes = APIRouter(prefix="/visits", tags=["passes"])
scans = APIRouter(prefix="/passes", tags=["passes"])


@visit_passes.post("/{visit_id}/pass", response_model=IssuedPassOut)
async def issue_pass(visit_id: str, request: Request, ctx: AuthContext = Depends(require(Permission.PASS_ISSUE)),
                     database: Database = Depends(get_database),
                     settings: Settings = Depends(get_settings)) -> IssuedPassOut:
    """Issues the visit's pass for printing. Calling it again (reprint) cancels the previous QR."""
    issued = await svc.issue(database.db, settings, ctx, request_meta(request), visit_id)
    return IssuedPassOut(qr_text=issued.qr_text, expires_at=issued.expires_at,
                         badge=BadgeOut.from_visit(issued.visit, settings.organization_name, issued.expires_at))


@visit_passes.post("/{visit_id}/pass/revoke", response_model=VisitOut)
async def revoke_pass(visit_id: str, request: Request, ctx: AuthContext = Depends(require(Permission.PASS_ISSUE)),
                      database: Database = Depends(get_database)) -> VisitOut:
    return VisitOut.from_doc(await svc.revoke(database.db, ctx, request_meta(request), visit_id))


@visit_passes.post("/{visit_id}/badge-print", status_code=204, response_class=Response)
async def badge_printed(visit_id: str, request: Request, ctx: AuthContext = Depends(require(Permission.PASS_ISSUE)),
                        database: Database = Depends(get_database)) -> Response:
    """Records that a badge was sent to the printer (the browser cannot confirm the paper came out)."""
    await svc.record_badge_print(database.db, ctx, request_meta(request), visit_id)
    return Response(status_code=204)


@scans.post("/resolve", response_model=ScanOut)
async def resolve_pass(body: ScannedPass, request: Request,
                       ctx: AuthContext = Depends(require(Permission.VISIT_CHECK_OUT)),
                       database: Database = Depends(get_database)) -> ScanOut:
    """Who a scanned pass belongs to. Changes nothing: the guard confirms before checking out."""
    visit = await svc.resolve(database.db, ctx, request_meta(request), body.qr_text)
    return ScanOut(status="VALID" if visit["status"] == "CHECKED_IN" else "CHECKED_OUT", visit=VisitOut.from_doc(visit))


@scans.post("/check-out", response_model=CheckOutResult)
async def check_out_with_pass(body: ScannedPass, request: Request,
                              ctx: AuthContext = Depends(require(Permission.VISIT_CHECK_OUT)),
                              database: Database = Depends(get_database)) -> CheckOutResult:
    visit, already = await svc.check_out(database.db, ctx, request_meta(request), body.qr_text)
    return CheckOutResult(visit=VisitOut.from_doc(visit), already_checked_out=already)
