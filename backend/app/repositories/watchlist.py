"""MongoDB access for the watchlist (queries only; identity normalisation and rules live in services)."""
import re
from datetime import datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.repositories.errors import duplicates_as_domain_error
from app.schemas.watchlist import WatchlistStatus

NEWEST_FIRST = [("created_at", -1), ("_id", -1)]


def _not_expired(now: datetime) -> dict:
    return {"$or": [{"expires_at": None}, {"expires_at": {"$gt": now}}]}


def _status_query(status: WatchlistStatus | None, now: datetime) -> dict:
    if status is WatchlistStatus.ACTIVE:
        return {"is_active": True, **_not_expired(now)}
    if status is WatchlistStatus.EXPIRED:
        return {"is_active": True, "expires_at": {"$lte": now}}
    if status is WatchlistStatus.DISABLED:
        return {"is_active": False}
    return {}


async def find_active_match(db: AsyncDatabase, identifiers: list[str], other_compact: str | None,
                            now: datetime) -> dict | None:
    """The active, unexpired entry whose identifier is one of `identifiers`, or (with `other_compact`) an
    "OTHER:" identifier equal to `other_compact` when spaces, / and - are ignored."""
    clauses: list[dict] = [{"identifier": {"$in": identifiers}}]
    if other_compact:
        # Letters and digits only, so nothing to escape; the fixed "OTHER:<first char>" prefix uses the index.
        clauses.append({"identifier": {"$regex": "^OTHER:" + "[ /-]*".join(other_compact) + "$"}})
    return await db.watchlist.find_one({"$and": [{"$or": clauses}, _not_expired(now)], "is_active": True})


async def list_page(db: AsyncDatabase, *, status: WatchlistStatus | None, now: datetime,
                    search_identifiers: list[str] | None, search_name_prefix: str | None,
                    after: tuple[datetime, ObjectId] | None, limit: int) -> list[dict]:
    """Newest first. With `search_name_prefix` (not None): entries with one of `search_identifiers` or
    a name starting with the prefix. `after`: the (created_at, ID) of the last row already shown."""
    clauses = [_status_query(status, now)]
    if search_name_prefix is not None:
        clauses.append({"$or": [{"identifier": {"$in": search_identifiers or []}},
                                {"name_search": {"$regex": "^" + re.escape(search_name_prefix)}}]})
    if after:
        last_at, last_id = after
        clauses.append({"$or": [{"created_at": {"$lt": last_at}}, {"created_at": last_at, "_id": {"$lt": last_id}}]})
    query = {"$and": [c for c in clauses if c]} if any(clauses) else {}
    return await db.watchlist.find(query).sort(NEWEST_FIRST).limit(limit).to_list(length=limit)


async def find_by_id(db: AsyncDatabase, entry_id: ObjectId) -> dict | None:
    return await db.watchlist.find_one({"_id": entry_id})


async def find_active_by_identifier(db: AsyncDatabase, identifier: str,
                                    session: AsyncClientSession | None = None) -> dict | None:
    """The entry with is_active (whether or not it has expired) for this identifier; at most one exists."""
    return await db.watchlist.find_one({"identifier": identifier, "is_active": True}, session=session)


async def insert(db: AsyncDatabase, doc: dict, session: AsyncClientSession | None = None) -> ObjectId:
    """Raises DuplicateKey if the identifier already has an is_active entry."""
    with duplicates_as_domain_error():
        return (await db.watchlist.insert_one(doc, session=session)).inserted_id


async def update_fields(db: AsyncDatabase, entry_id: ObjectId, fields: dict, *, only_if_active: bool,
                        session: AsyncClientSession | None = None) -> None:
    """Sets exactly `fields` (callers set updated_at/updated_by themselves)."""
    query: dict = {"_id": entry_id}
    if only_if_active:
        query["is_active"] = True
    await db.watchlist.update_one(query, {"$set": fields}, session=session)
