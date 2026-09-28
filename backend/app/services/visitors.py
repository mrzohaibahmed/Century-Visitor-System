"""
Visitors: the person, independent of any single visit.

- One visitor per identity document (enforced by a unique index).
- Opening a visitor's details or looking one up by ID number is audited
  (personal data access); audit records only ever hold masked ID numbers.
- Watchlist screening compares normalised identifiers, so formatting cannot
  bypass a ban, and it ignores the document type chosen at the gate: a banned
  CNIC typed in as a passport or "other ID" is still refused.
"""
import re
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.errors import AppError
from app.core.identity import (
    IdentityType,
    identifier,
    mask_identity,
    normalize_identity,
    normalize_phone,
    search_key,
)
from app.core.pagination import decode_cursor, encode_cursor
from app.db.transactions import run_in_transaction
from app.services import audit
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta

SEARCH_LIMIT = 25
NOT_FOUND = AppError(404, "not_found", "Visitor not found.")


def _oid(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise NOT_FOUND
    return ObjectId(value)


async def get(db: AsyncDatabase, visitor_id: str | ObjectId, session: AsyncClientSession | None = None) -> dict:
    oid = visitor_id if isinstance(visitor_id, ObjectId) else _oid(visitor_id)
    doc = await db.visitors.find_one({"_id": oid}, session=session)
    if doc is None:
        raise NOT_FOUND
    return doc


async def active_visit(db: AsyncDatabase, visitor_id: ObjectId) -> dict | None:
    return await db.visits.find_one({"visitor_id": visitor_id, "status": "CHECKED_IN"})


async def screening(db: AsyncDatabase, visitor: dict) -> dict | None:
    """The active, unexpired watchlist entry matching this visitor, if any."""
    ident = visitor.get("identity")
    if not ident:
        return None
    return await db.watchlist.find_one({
        "$and": [_watchlist_match(ident), {"$or": [{"expires_at": None}, {"expires_at": {"$gt": datetime.now(UTC)}}]}],
        "is_active": True,
    })


def _watchlist_match(ident: dict) -> dict:
    """Every watchlist identifier this document number could have been entered under, in any type.

    The type a guard picks is not proof of anything, so the number itself decides: "3520112345671" as a
    passport matches a CNIC ban, "AB12345" as another ID matches a passport ban, and so on. "Other" numbers
    keep spaces, / and - after normalisation, so they are compared with those separators ignored.
    """
    number = ident["number"]
    compact = re.sub(r"[^0-9A-Z]", "", number.upper())
    keys = {identifier(ident["type"], number)}
    keys.update(identifier(t, n) for value in {number, compact} for t, n in _identity_candidates(value))
    clauses: list[dict] = [{"identifier": {"$in": sorted(keys)}}]
    if compact:
        # Letters and digits only, so nothing to escape; the fixed "OTHER:<first char>" prefix uses the index.
        clauses.append({"identifier": {"$regex": "^OTHER:" + "[ /-]*".join(compact) + "$"}})
    return {"$or": clauses}


async def create(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, full_name: str, identity: dict,
                 phone: str | None) -> dict:
    now = datetime.now(UTC)
    doc = {"full_name": full_name, "name_search": search_key(full_name), "identity": identity, "phone": phone,
           "current_photo_id": None, "created_at": now, "updated_at": now, "created_by": ctx.user["_id"]}

    async def work(s: AsyncClientSession):
        doc["_id"] = (await db.visitors.insert_one(doc, session=s)).inserted_id
        await audit.record(db, AuditAction.VISITOR_CREATED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="visitor", resource_id=doc["_id"],
                           metadata={"identity_type": identity["type"],
                                     "identity": mask_identity(identity["number"])}, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKeyError:
        raise AppError(409, "visitor_exists", "A visitor with this ID number is already registered.") from None
    return doc


async def lookup(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, id_type: IdentityType,
                 raw_number: str) -> dict:
    try:
        number = normalize_identity(id_type, raw_number)
    except ValueError as e:
        raise AppError(422, "invalid_identity", str(e)) from None
    doc = await db.visitors.find_one({"identity.type": str(id_type), "identity.number": number})
    await audit.record(db, AuditAction.VISITOR_LOOKUP, actor=actor_from_user(ctx.user), ip=meta.ip,
                       resource_type="visitor", resource_id=doc["_id"] if doc else None,
                       metadata={"identity_type": str(id_type), "identity": mask_identity(number),
                                 "found": doc is not None})
    if doc is None:
        raise AppError(404, "not_found", "No visitor is registered with this ID number.")
    return doc


async def view(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, visitor_id: str) -> dict:
    doc = await get(db, visitor_id)
    await audit.record(db, AuditAction.VISITOR_VIEWED, actor=actor_from_user(ctx.user), ip=meta.ip,
                       resource_type="visitor", resource_id=doc["_id"])
    return doc


def _identity_candidates(q: str) -> list[tuple[str, str]]:
    found = []
    for id_type in IdentityType:
        try:
            found.append((str(id_type), normalize_identity(id_type, q)))
        except ValueError:
            continue
    return found


identity_candidates = _identity_candidates      # (type, normalised number) pairs a free-text query could be


async def search(db: AsyncDatabase, q: str, cursor: str | None = None) -> tuple[list[dict], str | None]:
    """By ID number or phone (exact), otherwise by name prefix (paginated)."""
    q = q.strip()
    if len(q) < 2:
        raise AppError(422, "query_too_short", "Type at least 2 characters to search.")

    exact: list[dict] = []
    if any(ch.isdigit() for ch in q):
        clauses = [{"identity.type": t, "identity.number": n} for t, n in _identity_candidates(q)]
        try:
            phone = normalize_phone(q)
            if phone:
                clauses.append({"phone": phone})
        except ValueError:
            pass
        if clauses:
            exact = await db.visitors.find({"$or": clauses}).limit(SEARCH_LIMIT).to_list(length=SEARCH_LIMIT)
    if exact:
        return exact, None

    query: dict = {"name_search": {"$regex": "^" + re.escape(search_key(q))}}
    if cursor:
        last_name, last_id = decode_cursor(cursor)
        query = {"$and": [query, {"$or": [{"name_search": {"$gt": last_name}},
                                          {"name_search": last_name, "_id": {"$gt": last_id}}]}]}
    docs = await db.visitors.find(query).sort([("name_search", 1), ("_id", 1)]).limit(SEARCH_LIMIT + 1) \
        .to_list(length=SEARCH_LIMIT + 1)
    next_cursor = None
    if len(docs) > SEARCH_LIMIT:
        docs = docs[:SEARCH_LIMIT]
        next_cursor = encode_cursor(docs[-1]["name_search"], docs[-1]["_id"])
    return docs, next_cursor


async def matching_ids(db: AsyncDatabase, q: str, limit: int = 200) -> list[ObjectId]:
    """Visitor ids matching a free-text query (for filtering visit history)."""
    q = q.strip()
    clauses: list[dict] = [{"name_search": {"$regex": "^" + re.escape(search_key(q))}}]
    clauses += [{"identity.type": t, "identity.number": n} for t, n in _identity_candidates(q)]
    try:
        phone = normalize_phone(q)
        if phone:
            clauses.append({"phone": phone})
    except ValueError:
        pass
    docs = await db.visitors.find({"$or": clauses}, {"_id": 1}).limit(limit).to_list(length=limit)
    return [d["_id"] for d in docs]


async def update(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, visitor_id: str, changes: dict) -> dict:
    current = await get(db, visitor_id)
    fields = {k: v for k, v in changes.items() if v is not None and v != current.get(k)}
    if not fields:
        return current
    if "full_name" in fields:
        fields["name_search"] = search_key(fields["full_name"])

    diff: dict = {}
    for key in ("full_name", "phone"):
        if key in fields:
            diff[key] = {"from": current.get(key), "to": fields[key]}
    if "identity" in fields:
        old = current.get("identity") or {}
        diff["identity"] = {"from": f"{old.get('type')}:{mask_identity(old.get('number', ''))}",
                            "to": f"{fields['identity']['type']}:{mask_identity(fields['identity']['number'])}"}

    async def work(s: AsyncClientSession):
        await db.visitors.update_one({"_id": current["_id"]},
                                     {"$set": {**fields, "updated_at": datetime.now(UTC)}}, session=s)
        await audit.record(db, AuditAction.VISITOR_UPDATED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="visitor", resource_id=current["_id"], changes=diff, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKeyError:
        raise AppError(409, "visitor_exists", "Another visitor is already registered with this ID number.") from None
    return await get(db, current["_id"])
