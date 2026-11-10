"""MongoDB access for the users collection (queries only; rules live in services)."""
from datetime import UTC, datetime, timedelta

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.db.schema import CASE_INSENSITIVE
from app.repositories.errors import duplicates_as_domain_error


def parse_id(value: str) -> ObjectId | None:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


async def find_by_username(db: AsyncDatabase, username: str) -> dict | None:
    # Case-insensitive, matching the unique index (so "Guard1" logs into "guard1").
    return await db.users.find_one({"username": username}, collation=CASE_INSENSITIVE)


async def find_by_id(db: AsyncDatabase, user_id: ObjectId, session: AsyncClientSession | None = None) -> dict | None:
    return await db.users.find_one({"_id": user_id}, session=session)


async def list_all(db: AsyncDatabase, limit: int = 500) -> list[dict]:
    cursor = db.users.find({}, {"password_hash": 0}).sort("username", 1).limit(limit)
    return await cursor.to_list(length=limit)


async def find_active_id(db: AsyncDatabase, user_id: ObjectId,
                         session: AsyncClientSession | None = None) -> ObjectId | None:
    """The ID back if that user exists and is active, otherwise None."""
    doc = await db.users.find_one({"_id": user_id, "is_active": True}, {"_id": 1}, session=session)
    return doc["_id"] if doc else None


async def display_names(db: AsyncDatabase, ids: set[ObjectId]) -> dict[ObjectId, str]:
    """Display name (or username when it has none) per user ID."""
    if not ids:
        return {}
    docs = await db.users.find({"_id": {"$in": list(ids)}}, {"username": 1, "display_name": 1}) \
        .to_list(length=len(ids))
    return {d["_id"]: d.get("display_name") or d["username"] for d in docs}


async def insert(db: AsyncDatabase, doc: dict, session: AsyncClientSession | None = None) -> ObjectId:
    """Raises DuplicateKey if the username exists (ignoring case)."""
    with duplicates_as_domain_error():
        result = await db.users.insert_one(doc, session=session)
    return result.inserted_id


async def update_fields(db: AsyncDatabase, user_id: ObjectId, fields: dict,
                        session: AsyncClientSession | None = None) -> None:
    fields = {**fields, "updated_at": datetime.now(UTC)}
    await db.users.update_one({"_id": user_id}, {"$set": fields}, session=session)


async def count_active_admins(db: AsyncDatabase, session: AsyncClientSession | None = None) -> int:
    return await db.users.count_documents({"role": "ADMIN", "is_active": True}, session=session)


async def claim_admin_guard(db: AsyncDatabase, session: AsyncClientSession) -> None:
    """Writes one shared document inside the transaction. Two concurrent transactions that
    both reduce the number of admins therefore conflict; the retry sees the other's change."""
    await db.counters.update_one({"_id": "admin_guard"}, {"$inc": {"seq": 1}}, upsert=True, session=session)


async def record_failed_login(db: AsyncDatabase, user_id: ObjectId, max_failures: int,
                              lockout_minutes: int) -> bool:
    """Atomic across gate PCs. Returns True if this failure locked the account."""
    doc = await db.users.find_one_and_update(
        {"_id": user_id}, {"$inc": {"failed_login_count": 1}}, return_document=ReturnDocument.AFTER)
    if doc and doc.get("failed_login_count", 0) >= max_failures:
        await db.users.update_one({"_id": user_id}, {"$set": {
            "locked_until": datetime.now(UTC) + timedelta(minutes=lockout_minutes), "failed_login_count": 0}})
        return True
    return False


async def record_successful_login(db: AsyncDatabase, user_id: ObjectId, new_hash: str | None) -> None:
    fields = {"failed_login_count": 0, "locked_until": None, "last_login_at": datetime.now(UTC)}
    if new_hash:
        fields["password_hash"] = new_hash
    await db.users.update_one({"_id": user_id}, {"$set": fields})
