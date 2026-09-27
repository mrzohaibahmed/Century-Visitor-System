"""MongoDB access for server-side sessions."""
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase


async def insert(db: AsyncDatabase, doc: dict) -> ObjectId:
    return (await db.sessions.insert_one(doc)).inserted_id


async def find_active_by_token_hash(db: AsyncDatabase, token_hash: str) -> dict | None:
    return await db.sessions.find_one({"token_hash": token_hash, "revoked_at": None})


async def touch(db: AsyncDatabase, session_id: ObjectId, now: datetime) -> None:
    await db.sessions.update_one({"_id": session_id}, {"$set": {"last_seen_at": now}})


async def revoke(db: AsyncDatabase, session_id: ObjectId, reason: str) -> None:
    await db.sessions.update_one({"_id": session_id, "revoked_at": None},
                                 {"$set": {"revoked_at": datetime.now(UTC), "revoked_reason": reason}})


async def revoke_all_for_user(db: AsyncDatabase, user_id: ObjectId, reason: str, *,
                              except_session_id: ObjectId | None = None,
                              session: AsyncClientSession | None = None) -> int:
    query: dict = {"user_id": user_id, "revoked_at": None}
    if except_session_id is not None:
        query["_id"] = {"$ne": except_session_id}
    result = await db.sessions.update_many(
        query, {"$set": {"revoked_at": datetime.now(UTC), "revoked_reason": reason}}, session=session)
    return result.modified_count
