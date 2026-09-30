"""Visitors: lookup by ID (check-in), search, create, details, admin edit."""
from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_database, request_meta, require
from app.core.identity import IdentityType
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.common import Page
from app.schemas.visitors import ScreeningOut, VisitorCreate, VisitorLookupOut, VisitorOut, VisitorUpdate
from app.schemas.visits import VisitOut
from app.services import entry_denials as entry_denials_svc
from app.services import visitors as svc
from app.services import visits as visits_svc
from app.services.auth import AuthContext

router = APIRouter(prefix="/visitors", tags=["visitors"])


def _lookup_out(doc: dict, active: dict | None, ban: dict | None) -> VisitorLookupOut:
    return VisitorLookupOut(
        visitor=VisitorOut.from_doc(doc, active),
        screening=ScreeningOut(status="BLOCKED", reason=ban["reason"]) if ban else ScreeningOut(status="CLEAR"))


async def _with_status(database: Database, doc: dict) -> VisitorLookupOut:
    active = await svc.active_visit(database.db, doc["_id"])
    return _lookup_out(doc, active, await svc.screening(database.db, doc))


@router.get("", response_model=Page[VisitorOut])
async def search_visitors(q: str = Query(min_length=2, max_length=100), cursor: str | None = None,
                          ctx: AuthContext = Depends(require(Permission.VISITOR_READ)),
                          database: Database = Depends(get_database)) -> Page[VisitorOut]:
    docs, next_cursor = await svc.search(database.db, q, cursor)
    return Page[VisitorOut](items=[VisitorOut.from_doc(d) for d in docs], next_cursor=next_cursor)


@router.get("/lookup", response_model=VisitorLookupOut)
async def lookup_visitor(request: Request, id_type: IdentityType, id_number: str = Query(max_length=60),
                         ctx: AuthContext = Depends(require(Permission.VISITOR_READ)),
                         database: Database = Depends(get_database)) -> VisitorLookupOut:
    """Check-in step 1: is this person already registered, inside, or on the watchlist?
    A BLOCKED answer refuses the entry at the gate, so it is audited and recorded as a denial (the answer
    itself is unchanged). The visitor details view (GET /visitors/{id}) screens too but records nothing."""
    meta = request_meta(request)
    doc = await svc.lookup(database.db, ctx, meta, id_type, id_number)
    active = await svc.active_visit(database.db, doc["_id"])
    ban = await svc.screening(database.db, doc)
    if ban:
        await entry_denials_svc.record_blocked_lookup(database.db, ctx, meta, doc, ban)
    return _lookup_out(doc, active, ban)


@router.post("", response_model=VisitorOut, status_code=201)
async def create_visitor(body: VisitorCreate, request: Request,
                         ctx: AuthContext = Depends(require(Permission.VISITOR_CREATE)),
                         database: Database = Depends(get_database)) -> VisitorOut:
    doc = await svc.create(database.db, ctx, request_meta(request), body.full_name,
                           body.identity.model_dump(mode="json"), body.phone)
    return VisitorOut.from_doc(doc)


@router.get("/{visitor_id}", response_model=VisitorLookupOut)
async def get_visitor(visitor_id: str, request: Request,
                      ctx: AuthContext = Depends(require(Permission.VISITOR_READ)),
                      database: Database = Depends(get_database)) -> VisitorLookupOut:
    doc = await svc.view(database.db, ctx, request_meta(request), visitor_id)
    return await _with_status(database, doc)


@router.patch("/{visitor_id}", response_model=VisitorOut)
async def update_visitor(visitor_id: str, body: VisitorUpdate, request: Request,
                         ctx: AuthContext = Depends(require(Permission.VISITOR_EDIT)),
                         database: Database = Depends(get_database)) -> VisitorOut:
    changes = body.model_dump(mode="json", exclude_none=True)
    doc = await svc.update(database.db, ctx, request_meta(request), visitor_id, changes)
    return VisitorOut.from_doc(doc, await svc.active_visit(database.db, doc["_id"]))


@router.get("/{visitor_id}/visits", response_model=Page[VisitOut])
async def visitor_visits(visitor_id: str, request: Request, cursor: str | None = None,
                         ctx: AuthContext = Depends(require(Permission.VISIT_READ)),
                         database: Database = Depends(get_database)) -> Page[VisitOut]:
    visitor = await svc.get(database.db, visitor_id)
    docs, next_cursor = await visits_svc.list_visits(
        database.db, request.app.state.settings, status=None, day_from=None, day_to=None, host_id=None,
        department_id=None, gate_id=None, visitor_id=str(visitor["_id"]), q=None, cursor=cursor, limit=25)
    return Page[VisitOut](items=[VisitOut.from_doc(d) for d in docs], next_cursor=next_cursor)
