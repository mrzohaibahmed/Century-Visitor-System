"""MongoDB access for visitors (queries only; matching rules and normalisation live in services)."""
import re
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.repositories.errors import duplicates_as_domain_error

NAME_ORDER = [("name_search", 1), ("_id", 1)]


def _prefix(value: str) -> dict:
    return {"$regex": "^" + re.escape(value)}


def _identity_or_phone(identities: list[tuple[str, str]], phone: str | None) -> list[dict]:
    clauses: list[dict] = [{"identity.type": t, "identity.number": n} for t, n in identities]
    if phone:
        clauses.append({"phone": phone})
    return clauses


async def find_by_id(db: AsyncDatabase, visitor_id: ObjectId, session: AsyncClientSession | None = None
                     ) -> dict | None:
    return await db.visitors.find_one({"_id": visitor_id}, session=session)


async def find_by_identity(db: AsyncDatabase, id_type: str, number: str) -> dict | None:
    """The visitor with exactly this (already normalised) document."""
    return await db.visitors.find_one({"identity.type": id_type, "identity.number": number})


async def find_exact(db: AsyncDatabase, identities: list[tuple[str, str]], phone: str | None,
                     limit: int) -> list[dict]:
    """Visitors with any of these documents or this phone number, in name order."""
    clauses = _identity_or_phone(identities, phone)
    if not clauses:
        return []
    return await db.visitors.find({"$or": clauses}).sort(NAME_ORDER).limit(limit).to_list(length=limit)


async def list_by_name(db: AsyncDatabase, *, name_prefix: str | None, after: tuple[str, ObjectId] | None,
                       limit: int) -> list[dict]:
    """Name order (search key, then ID). `after`: the (search key, ID) of the last row already shown."""
    query: dict = {"name_search": _prefix(name_prefix)} if name_prefix is not None else {}
    if after:
        last_name, last_id = after
        later = {"$or": [{"name_search": {"$gt": last_name}}, {"name_search": last_name, "_id": {"$gt": last_id}}]}
        query = {"$and": [query, later]} if query else later
    return await db.visitors.find(query).sort(NAME_ORDER).limit(limit).to_list(length=limit)


async def matching_ids(db: AsyncDatabase, *, name_prefix: str, identities: list[tuple[str, str]],
                       phone: str | None, limit: int) -> list[ObjectId]:
    """IDs of visitors whose name starts with `name_prefix` or who have one of these documents or this phone."""
    clauses = [{"name_search": _prefix(name_prefix)}, *_identity_or_phone(identities, phone)]
    docs = await db.visitors.find({"$or": clauses}, {"_id": 1}).limit(limit).to_list(length=limit)
    return [d["_id"] for d in docs]


async def has_current_photo(db: AsyncDatabase, visitor_id: ObjectId, photo_id: ObjectId) -> bool:
    return bool(await db.visitors.count_documents({"_id": visitor_id, "current_photo_id": photo_id}, limit=1))


async def insert(db: AsyncDatabase, doc: dict, session: AsyncClientSession | None = None) -> ObjectId:
    """Raises DuplicateKey if a visitor with this document already exists."""
    with duplicates_as_domain_error():
        return (await db.visitors.insert_one(doc, session=session)).inserted_id


async def update_fields(db: AsyncDatabase, visitor_id: ObjectId, fields: dict,
                        session: AsyncClientSession | None = None, *, now: datetime | None = None) -> None:
    """Sets `fields` and updated_at (default: now). Raises DuplicateKey for a document already registered."""
    with duplicates_as_domain_error():
        await db.visitors.update_one({"_id": visitor_id},
                                     {"$set": {**fields, "updated_at": now or datetime.now(UTC)}}, session=session)
