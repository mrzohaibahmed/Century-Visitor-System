"""MongoDB access for notifications: the in-app inbox and the e-mail queue (queries only)."""
from datetime import datetime

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.repositories.errors import duplicates_as_domain_error

NEWEST_FIRST = [("created_at", -1), ("_id", -1)]


async def insert(db: AsyncDatabase, doc: dict, session: AsyncClientSession | None = None) -> ObjectId:
    """Raises DuplicateKey if a notification with this event_key exists (one per visit and kind)."""
    with duplicates_as_domain_error():
        return (await db.notifications.insert_one(doc, session=session)).inserted_id


# --- in-app inbox (always restricted to one recipient) ---

def _mine(user_id: ObjectId) -> dict:
    return {"recipient_user_id": user_id}


async def list_for_recipient(db: AsyncDatabase, user_id: ObjectId, *, unread_only: bool,
                             after: tuple[datetime, ObjectId] | None, limit: int) -> list[dict]:
    """Newest first. `after`: the (created_at, ID) of the last row already shown."""
    query: dict = _mine(user_id) | ({"read_at": None} if unread_only else {})
    if after:
        last_at, last_id = after
        query = {"$and": [query, {"$or": [{"created_at": {"$lt": last_at}},
                                          {"created_at": last_at, "_id": {"$lt": last_id}}]}]}
    return await db.notifications.find(query).sort(NEWEST_FIRST).limit(limit).to_list(length=limit)


async def count_unread(db: AsyncDatabase, user_id: ObjectId) -> int:
    return await db.notifications.count_documents(_mine(user_id) | {"read_at": None})


async def find_for_recipient(db: AsyncDatabase, user_id: ObjectId, notification_id: ObjectId) -> dict | None:
    return await db.notifications.find_one(_mine(user_id) | {"_id": notification_id})


async def mark_read(db: AsyncDatabase, user_id: ObjectId, notification_id: ObjectId, now: datetime) -> None:
    """Sets read_at if still unread (idempotent); someone else's notification is not touched."""
    await db.notifications.update_one(_mine(user_id) | {"_id": notification_id, "read_at": None},
                                      {"$set": {"read_at": now}})


async def mark_all_read(db: AsyncDatabase, user_id: ObjectId, now: datetime) -> int:
    result = await db.notifications.update_many(_mine(user_id) | {"read_at": None}, {"$set": {"read_at": now}})
    return result.modified_count


# --- e-mail queue ---

async def fail_expired_claims(db: AsyncDatabase, now: datetime) -> None:
    """E-mails still SENDING after their lease (a crashed send) become FAILED, never sent again."""
    await db.notifications.update_many(
        {"email.status": "SENDING", "email.lease_until": {"$lt": now}},
        {"$set": {"email.status": "FAILED", "email.error": "interrupted", "email.lease_until": None,
                  "email.next_attempt_at": None}})


async def claim_next_due(db: AsyncDatabase, now: datetime, lease_until: datetime) -> dict | None:
    """Atomically moves the earliest due PENDING e-mail to SENDING (one attempt more) and returns it;
    several API processes never claim the same one. None when nothing is due."""
    return await db.notifications.find_one_and_update(
        {"email.status": "PENDING", "email.next_attempt_at": {"$lte": now}},
        {"$set": {"email.status": "SENDING", "email.lease_until": lease_until, "email.last_attempt_at": now},
         "$inc": {"email.attempts": 1}},
        sort=[("email.next_attempt_at", 1)], return_document=ReturnDocument.AFTER)


async def finish_claim(db: AsyncDatabase, notification_id: ObjectId, attempt: int, email_fields: dict) -> None:
    """Records the result of an attempt, only while that attempt still holds the claim. `email_fields`
    (status, error, next_attempt_at, sent_at) are set on the e-mail; the lease is cleared."""
    await db.notifications.update_one(
        {"_id": notification_id, "email.status": "SENDING", "email.attempts": attempt},
        {"$set": {f"email.{k}": v for k, v in email_fields.items()} | {"email.lease_until": None}})
