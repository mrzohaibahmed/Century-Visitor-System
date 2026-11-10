"""
Check-in, check-out and visit history.

Check-in is one transaction: visit number, visit and audit record succeed or
fail together. The business rules are enforced on the server:
- the gate and operator come from the session, never from the request;
- watchlist screening blocks the entry (and is audited);
- at most one active visit per visitor (a partial unique index in MongoDB, so
  two gates checking in the same person at once cannot both succeed).
Check-out is a single conditional update: atomic and idempotent.
"""
from datetime import UTC, date, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.core.identity import identifier, mask_identity
from app.core.pagination import decode_cursor, encode_cursor
from app.core.timeutil import day_bounds_utc, local_today
from app.db.transactions import run_in_transaction
from app.repositories import photos as photos_repo
from app.repositories import visitors as visitors_repo
from app.repositories import visits as visits_repo
from app.repositories.errors import DuplicateKey
from app.repositories.ids import parse_id
from app.repositories.visits import VisitFilter  # noqa: F401 (re-exported: reports and tests import it from here)
from app.schemas.visits import VISIT_NUMBER, CheckInRequest, UpdateBelongingsRequest
from app.services import audit
from app.services import directory as directory_svc
from app.services import entry_denials as entry_denials_svc
from app.services import notifications as notifications_svc
from app.services import photos as photos_svc
from app.services import visitors as visitors_svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta, session_gate

ACTIVE_LIMIT = 500
PAGE_LIMIT_MAX = 100
NOT_FOUND = AppError(404, "not_found", "Visit not found.")
# Month in visit numbers: fixed English capitals, whatever the server's locale.
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _oid(value: str) -> ObjectId:
    oid = parse_id(value)
    if oid is None:
        raise NOT_FOUND
    return oid


object_id = _oid


def _operator_name(user: dict) -> str:
    return user.get("display_name") or user["username"]


async def _require_gate(db: AsyncDatabase, ctx: AuthContext) -> dict:
    gate, selection_required = await session_gate(db, ctx.session)
    if gate:
        return gate
    if selection_required:
        raise AppError(409, "gate_required", "Choose the gate you are working at before checking visitors in.")
    raise AppError(409, "no_gate_configured", "No gate is set up yet. An administrator must add a gate first.")


async def check_in(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
                   body: CheckInRequest) -> dict:
    gate = await _require_gate(db, ctx)
    visitor = await visitors_svc.get(db, body.visitor_id)
    actor = actor_from_user(ctx.user)

    ban = await visitors_svc.screening(db, visitor)
    if ban:
        ident = visitor["identity"]
        match = await audit.record(db, AuditAction.WATCHLIST_MATCH, actor=actor, ip=meta.ip, resource_type="visitor",
                                   resource_id=visitor["_id"],
                                   metadata={"watchlist_id": ban["_id"], "gate_id": gate["_id"],
                                             "identifier": f"{ident['type']}:{mask_identity(ident['number'])}"})
        await audit.record(db, AuditAction.VISIT_CHECKED_IN, result="DENIED", actor=actor, ip=meta.ip,
                           resource_type="visitor", resource_id=visitor["_id"], metadata={"reason": "watchlist"})
        # Reporting only, best effort and time-limited: it never raises, so the refusal below is unchanged.
        await entry_denials_svc.record_check_in_denial(db, match=match, visitor=visitor, ban=ban, gate=gate,
                                                       user=ctx.user, reason_code=body.reason_code)
        raise AppError(403, "entry_denied",
                       f"Entry not permitted: {ban['reason']} "
                       "Do not admit this visitor; inform the security supervisor.")

    if body.host_id:
        host: dict | None = await directory_svc.get_active(db, directory_svc.HOST, body.host_id)
        host_id, host_name, host_department = host["_id"], host["name"], host.get("department_id")
    else:
        host = None             # an unlisted host has no directory entry: nobody to notify (flagged for review)
        host_id, host_name, host_department = None, body.unlisted_host_name, None

    department_id = body.department_id or host_department
    if not department_id:
        raise AppError(422, "department_required", "Choose the department being visited.")
    department = await directory_svc.get_active(db, directory_svc.DEPARTMENT, department_id)
    photo_id = await photos_svc.for_check_in(db, visitor, body.photo_id) if body.photo_id else None

    now = datetime.now(UTC)
    day = local_today(settings.timezone, now)
    visit = {
        "visitor_id": visitor["_id"], "host_id": host_id, "host_unlisted": host_id is None,
        "department_id": department["_id"], "gate_id": gate["_id"], "checkout_gate_id": None,
        "reason_code": str(body.reason_code), "reason_note": body.reason_note,
        "vehicle_registration": body.vehicle_registration, "belongings": body.belongings,
        "personal_material": body.personal_material.model_dump(mode="json") if body.personal_material else None,
        "status": "CHECKED_IN", "check_in_at": now, "check_out_at": None,
        "checked_in_by": ctx.user["_id"], "checked_out_by": None, "checkout_method": None, "pass": None,
        "photo_id": photo_id,
        "snapshot": {"visitor_name": visitor["full_name"], "host_name": host_name,
                     "department_name": department["name"], "gate_name": gate["name"],
                     "checked_in_by_name": _operator_name(ctx.user)},
        "created_at": now, "updated_at": now,
    }

    async def work(s: AsyncClientSession):
        # Counted per day at the gate: V-26-OCT-02-001 is the first visit on 2 October 2026.
        seq = await visits_repo.next_daily_number(db, day, session=s)
        visit["visit_number"] = f"V-{day:%y}-{MONTHS[day.month - 1]}-{day:%d}-{seq:03d}"
        visit["_id"] = await visits_repo.insert(db, visit, session=s)
        if photo_id:
            # The visit where the photo was taken (a later visit may reuse the visitor's current photo).
            await photos_repo.link_first_visit(db, photo_id, visit["_id"], session=s)
        await audit.record(db, AuditAction.VISIT_CHECKED_IN, actor=actor, ip=meta.ip, resource_type="visit",
                           resource_id=visit["_id"],
                           metadata={"visit_number": visit["visit_number"], "visitor_id": visitor["_id"],
                                     "gate_id": gate["_id"], "host_unlisted": host_id is None,
                                     "photo_id": photo_id}, session=s)
        if host is not None:
            # Same transaction: the notification exists exactly when the visit does. E-mail is sent later.
            await notifications_svc.create_host_arrival(db, settings, visit, host, session=s)
        await notifications_svc.create_department_arrival(db, settings, visit, department, host, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKey:
        existing = await visitors_svc.active_visit(db, visitor["_id"])
        number = f" (visit {existing['visit_number']})" if existing else ""
        raise AppError(409, "already_inside",
                       f"{visitor['full_name']} is already checked in{number}. Check them out first.") from None
    return visit


async def check_out(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, visit_id: ObjectId | str,
                    method: str = "MANUAL") -> tuple[dict, bool]:
    """Returns (visit, already_checked_out). Repeating a check-out changes nothing."""
    oid = _oid(visit_id)
    gate, _ = await session_gate(db, ctx.session)
    now = datetime.now(UTC)
    gate_id = gate["_id"] if gate else None
    result: dict = {}

    async def work(s: AsyncClientSession):
        # The status condition makes this atomic: only one request can move CHECKED_IN -> CHECKED_OUT.
        doc = await visits_repo.check_out_if_active(
            db, oid, now=now, user_id=ctx.user["_id"], user_name=_operator_name(ctx.user), gate_id=gate_id,
            gate_name=gate["name"] if gate else None, method=method, session=s)
        if doc is not None:
            await audit.record(db, AuditAction.VISIT_CHECKED_OUT, actor=actor_from_user(ctx.user), ip=meta.ip,
                               resource_type="visit", resource_id=oid,
                               metadata={"visit_number": doc["visit_number"], "method": method,
                                         "gate_id": gate_id}, session=s)
        result["doc"] = doc

    await run_in_transaction(db, work)
    if result["doc"] is not None:
        return result["doc"], False
    existing = await visits_repo.find_by_id(db, oid)
    if existing is None:
        raise NOT_FOUND
    if existing["status"] == "CHECKED_OUT":
        return existing, True
    raise AppError(409, "not_checked_in", "This visit is not currently checked in.")


async def resolve_and_check_out(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, *,
                                visit_number: str | None, identity: dict | None) -> tuple[dict, bool]:
    if visit_number:
        visit = await visits_repo.find_by_number(db, visit_number)
        if visit is None:
            raise AppError(404, "not_found", f"No visit {visit_number} was found.")
        if visit["status"] != "CHECKED_IN":
            return visit, True
        return await check_out(db, ctx, meta, visit["_id"], "VISIT_NUMBER")
    visitor = await visitors_repo.find_by_identity(db, identity["type"], identity["number"])
    active = await visitors_svc.active_visit(db, visitor["_id"]) if visitor else None
    if active is None:
        raise AppError(404, "not_inside", "No visitor with this ID number is currently inside.")
    return await check_out(db, ctx, meta, active["_id"], "ID_NUMBER")


async def get_visit(db: AsyncDatabase, visit_id: str) -> dict:
    doc = await visits_repo.find_by_id(db, _oid(visit_id), hide_pass_secrets=True)
    if doc is None:
        raise NOT_FOUND
    return doc


async def update_belongings(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta,
                            visit_id: str, body: UpdateBelongingsRequest) -> dict:
    """Replace belongings (and optional vehicle) on a visit that is still checked in."""
    oid = _oid(visit_id)
    now = datetime.now(UTC)
    set_material = "personal_material" in body.model_fields_set
    material = body.personal_material.model_dump(mode="json") if set_material and body.personal_material else None

    async def work(s: AsyncClientSession):
        doc = await visits_repo.update_belongings_if_active(
            db, oid, belongings=list(body.belongings), vehicle_registration=body.vehicle_registration,
            set_personal_material=set_material, personal_material=material, now=now, session=s)
        if doc is None:
            return
        await audit.record(db, AuditAction.VISIT_BELONGINGS_UPDATED, actor=actor_from_user(ctx.user),
                           ip=meta.ip, resource_type="visit", resource_id=oid,
                           metadata={"visit_number": doc["visit_number"],
                                     "belongings_count": len(body.belongings),
                                     "has_vehicle": body.vehicle_registration is not None}, session=s)
        return doc

    updated = await run_in_transaction(db, work)
    if updated is not None:
        return updated
    existing = await visits_repo.find_by_id(db, oid, hide_pass_secrets=True)
    if existing is None:
        raise NOT_FOUND
    raise AppError(409, "not_checked_in",
                   "Belongings can only be updated while the visitor is still inside.")


async def list_active(db: AsyncDatabase) -> tuple[list[dict], int]:
    docs = await visits_repo.list_active(db, ACTIVE_LIMIT)
    total = len(docs) if len(docs) < ACTIVE_LIMIT else await visits_repo.count_active(db)
    return docs, total


TOO_BROAD = AppError(422, "search_too_broad", "Too many visitors match this search. Type more of the name, "
                                              "or search by ID number, phone or visit number.")


async def visit_query(db: AsyncDatabase, f: VisitFilter, *, max_visitor_matches: int | None = None) -> dict:
    """The database filter for `f` (visits_repo.filter_query), with the free-text search resolved here.

    `q`: a visit number is matched exactly; anything else finds visitors by name prefix, ID number or
    phone (visitors.matching_ids). The visit history keeps its silent cap of 200 matching visitors;
    reports pass max_visitor_matches and get "search_too_broad" instead of a quietly incomplete result.
    """
    visit_number, ids = None, None
    if f.q and f.q.strip():
        term = f.q.strip().upper()
        if VISIT_NUMBER.match(term):
            visit_number = term
        else:
            if max_visitor_matches is None:
                ids = await visitors_svc.matching_ids(db, f.q)
            else:
                ids = await visitors_svc.matching_ids(db, f.q, limit=max_visitor_matches + 1)
                if len(ids) > max_visitor_matches:
                    raise TOO_BROAD
            if f.visitor_id:              # one visitor's visits, searched: both must hold
                ids = [i for i in ids if i == f.visitor_id]
    return visits_repo.filter_query(f, visit_number=visit_number, visitor_ids=ids)


async def list_visits(db: AsyncDatabase, settings: Settings, *, status: str | None, day_from: date | None,
                      day_to: date | None, host_id: str | None, department_id: str | None, gate_id: str | None,
                      visitor_id: str | None, q: str | None, cursor: str | None, limit: int
                      ) -> tuple[list[dict], str | None]:
    limit = max(1, min(limit, PAGE_LIMIT_MAX))
    start, end = day_bounds_utc(day_from, day_to, settings.timezone)
    # A malformed id is "not found" here (unchanged); the report endpoints validate ids before this point.
    query = await visit_query(db, VisitFilter(
        start=start, end=end, status=status, host_id=_oid(host_id) if host_id else None,
        department_id=_oid(department_id) if department_id else None, gate_id=_oid(gate_id) if gate_id else None,
        visitor_id=_oid(visitor_id) if visitor_id else None, q=q))

    docs = await visits_repo.list_page(db, query, after=decode_cursor(cursor) if cursor else None, limit=limit + 1)
    next_cursor = None
    if len(docs) > limit:
        docs = docs[:limit]
        next_cursor = encode_cursor(docs[-1]["check_in_at"], docs[-1]["_id"])
    return docs, next_cursor


def watchlist_identifier(visitor: dict) -> str | None:
    ident = visitor.get("identity")
    return identifier(ident["type"], ident["number"]) if ident else None
