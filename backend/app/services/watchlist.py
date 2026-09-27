"""
Watchlist management (administrators).

Screening itself (blocking a check-in) lives in services/visitors.screening()
and services/visits.check_in(); this module only maintains the entries.

- Identity numbers are normalised on the server (the same normalize_identity()
  used at check-in), so an entry matches the person in any spelling.
- Entries are never deleted. "Disable" lifts a ban; "expire" ends it now; both
  keep the entry for the record. The database allows one active entry per
  identity; adding a new entry for someone whose old entry has expired retires
  the old one in the same transaction.
- Every change is audited with a masked ID number.
"""
import re
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.errors import AppError
from app.core.identity import identifier, mask_identity, search_key
from app.core.pagination import decode_cursor, encode_cursor
from app.db.transactions import run_in_transaction
from app.schemas.watchlist import WatchlistStatus, status_of
from app.services import audit
from app.services import visitors as visitors_svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta

PAGE_SIZE = 25
NOT_FOUND = AppError(404, "not_found", "Watchlist entry not found.")


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise NOT_FOUND
    return ObjectId(value)


def _masked(doc_or_identity: dict) -> str:
    ident = doc_or_identity.get("identity", doc_or_identity)
    return f"{ident['type']}:{mask_identity(ident['number'])}"


def _operator_name(user: dict) -> str:
    return user.get("display_name") or user["username"]


def _status_query(status: WatchlistStatus | None, now: datetime) -> dict:
    if status is WatchlistStatus.ACTIVE:
        return {"is_active": True, "$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}
    if status is WatchlistStatus.EXPIRED:
        return {"is_active": True, "expires_at": {"$lte": now}}
    if status is WatchlistStatus.DISABLED:
        return {"is_active": False}
    return {}


async def list_entries(db: AsyncDatabase, *, q: str | None, status: WatchlistStatus | None,
                       cursor: str | None) -> tuple[list[dict], str | None]:
    """Newest first. `q` matches an ID number (any format) exactly or a name by prefix."""
    now = datetime.now(UTC)
    clauses = [_status_query(status, now)]
    if q and q.strip():
        term = q.strip()
        ids = [identifier(t, n) for t, n in visitors_svc.identity_candidates(term)]
        clauses.append({"$or": [{"identifier": {"$in": ids}},
                                {"name_search": {"$regex": "^" + re.escape(search_key(term))}}]})
    if cursor:
        last_at, last_id = decode_cursor(cursor)
        clauses.append({"$or": [{"created_at": {"$lt": last_at}}, {"created_at": last_at, "_id": {"$lt": last_id}}]})
    query = {"$and": [c for c in clauses if c]} if any(clauses) else {}
    docs = await db.watchlist.find(query).sort([("created_at", -1), ("_id", -1)]).limit(PAGE_SIZE + 1) \
        .to_list(length=PAGE_SIZE + 1)
    next_cursor = None
    if len(docs) > PAGE_SIZE:
        docs = docs[:PAGE_SIZE]
        next_cursor = encode_cursor(docs[-1]["created_at"], docs[-1]["_id"])
    return docs, next_cursor


async def get(db: AsyncDatabase, entry_id: str) -> dict:
    doc = await db.watchlist.find_one({"_id": _oid(entry_id)})
    if doc is None:
        raise NOT_FOUND
    return doc


async def create(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, *, identity: dict, name: str | None,
                 reason: str, expires_at: datetime | None) -> tuple[dict, str | None]:
    """Returns (entry, visit number if the person is inside right now)."""
    key = identifier(identity["type"], identity["number"])
    visitor = await db.visitors.find_one({"identity.type": identity["type"], "identity.number": identity["number"]})
    name = name or (visitor["full_name"] if visitor else None)
    now = datetime.now(UTC)
    doc = {
        "identifier": key, "identity": identity, "name": name, "name_search": search_key(name) if name else None,
        "reason": reason, "is_active": True, "expires_at": expires_at,
        "created_by": ctx.user["_id"], "created_by_name": _operator_name(ctx.user), "created_at": now,
        "updated_by": None, "updated_at": None, "disabled_by": None, "disabled_at": None, "disabled_reason": None,
    }

    async def work(s: AsyncClientSession):
        current = await db.watchlist.find_one({"identifier": key, "is_active": True}, session=s)
        superseded = None
        if current is not None:
            if status_of(current, now) is WatchlistStatus.ACTIVE:
                raise AppError(409, "already_listed", "This person already has an active watchlist entry. "
                                                      "Edit that entry instead.")
            # The old entry has expired: retire it so the new one can take its place.
            await db.watchlist.update_one({"_id": current["_id"]}, {"$set": {
                "is_active": False, "disabled_at": now, "disabled_by": ctx.user["_id"],
                "disabled_by_name": _operator_name(ctx.user), "disabled_reason": "Replaced by a new entry."}},
                session=s)
            superseded = current["_id"]
        doc.pop("_id", None)
        doc["_id"] = (await db.watchlist.insert_one(doc, session=s)).inserted_id
        await audit.record(db, AuditAction.WATCHLIST_ADDED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="watchlist", resource_id=doc["_id"],
                           metadata={"identifier": _masked(identity), "expires_at": expires_at,
                                     "replaces": superseded}, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKeyError:        # another administrator added the same person at the same moment
        raise AppError(409, "already_listed", "This person already has an active watchlist entry.") from None

    inside = await visitors_svc.active_visit(db, visitor["_id"]) if visitor else None
    return doc, inside["visit_number"] if inside else None


async def update(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, entry_id: str, *, name: str | None,
                 reason: str | None, expires_at: datetime | None, clear_expiry: bool) -> dict:
    current = await get(db, entry_id)
    if not current["is_active"]:
        raise AppError(409, "entry_disabled", "A disabled entry cannot be changed. Add a new entry instead.")
    fields: dict = {}
    if name is not None and name != current.get("name"):
        fields.update(name=name, name_search=search_key(name))
    if reason is not None and reason != current["reason"]:
        fields["reason"] = reason
    if clear_expiry and current.get("expires_at") is not None:
        fields["expires_at"] = None
    elif expires_at is not None and expires_at != current.get("expires_at"):
        fields["expires_at"] = expires_at
    if not fields:
        return current
    now = datetime.now(UTC)
    diff = {k: {"from": current.get(k), "to": v} for k, v in fields.items() if k != "name_search"}

    async def work(s: AsyncClientSession):
        await db.watchlist.update_one({"_id": current["_id"], "is_active": True},
                                      {"$set": {**fields, "updated_at": now, "updated_by": ctx.user["_id"]}},
                                      session=s)
        await audit.record(db, AuditAction.WATCHLIST_UPDATED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="watchlist", resource_id=current["_id"], changes=diff,
                           metadata={"identifier": _masked(current)}, session=s)

    await run_in_transaction(db, work)
    return await get(db, entry_id)


async def expire(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, entry_id: str) -> dict:
    """Ends the ban now (the entry stays, marked expired). Repeating it changes nothing."""
    current = await get(db, entry_id)
    now = datetime.now(UTC)
    if status_of(current, now) is not WatchlistStatus.ACTIVE:
        return current

    async def work(s: AsyncClientSession):
        await db.watchlist.update_one({"_id": current["_id"], "is_active": True},
                                      {"$set": {"expires_at": now, "updated_at": now, "updated_by": ctx.user["_id"]}},
                                      session=s)
        await audit.record(db, AuditAction.WATCHLIST_EXPIRED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="watchlist", resource_id=current["_id"],
                           changes={"expires_at": {"from": current.get("expires_at"), "to": now}},
                           metadata={"identifier": _masked(current)}, session=s)

    await run_in_transaction(db, work)
    return await get(db, entry_id)


async def disable(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, entry_id: str, note: str) -> dict:
    """Lifts the ban (kept for the record, with the reason). Repeating it changes nothing."""
    current = await get(db, entry_id)
    if not current["is_active"]:
        return current
    now = datetime.now(UTC)

    async def work(s: AsyncClientSession):
        await db.watchlist.update_one({"_id": current["_id"], "is_active": True}, {"$set": {
            "is_active": False, "disabled_at": now, "disabled_by": ctx.user["_id"],
            "disabled_by_name": _operator_name(ctx.user), "disabled_reason": note,
            "updated_at": now, "updated_by": ctx.user["_id"]}}, session=s)
        await audit.record(db, AuditAction.WATCHLIST_DISABLED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="watchlist", resource_id=current["_id"],
                           metadata={"identifier": _masked(current), "note": note}, session=s)

    await run_in_transaction(db, work)
    return await get(db, entry_id)
