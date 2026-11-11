"""MongoDB access for the `settings` collection: small documents stored under a fixed key
("email_smtp", "gate_camera:<gate id>", "schema"). Queries only; validation lives in services."""
from collections.abc import Iterable
from datetime import datetime

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase


async def get(db: AsyncDatabase, key: str, session: AsyncClientSession | None = None) -> dict | None:
    """The document stored under `key` (its _id), or None."""
    return await db.settings.find_one({"_id": key}, session=session)


async def get_many(db: AsyncDatabase, keys: list[str]) -> list[dict]:
    return await db.settings.find({"_id": {"$in": keys}}).to_list(length=len(keys))


async def upsert(db: AsyncDatabase, key: str, fields: dict, *, now: datetime, remove: Iterable[str] = (),
                 session: AsyncClientSession | None = None) -> None:
    """Sets `fields` on the document under `key` (created with created_at=now if missing) and removes the
    fields named in `remove`. Fields not mentioned are kept."""
    update: dict = {"$set": fields, "$setOnInsert": {"created_at": now}}
    removed = dict.fromkeys(remove, "")
    if removed:
        update["$unset"] = removed
    await db.settings.update_one({"_id": key}, update, upsert=True, session=session)


async def set_fields(db: AsyncDatabase, key: str, fields: dict) -> None:
    """Sets `fields` on an existing document (nothing happens if there is none)."""
    await db.settings.update_one({"_id": key}, {"$set": fields})


async def delete(db: AsyncDatabase, key: str, session: AsyncClientSession | None = None) -> bool:
    """True if a document was deleted."""
    return (await db.settings.delete_one({"_id": key}, session=session)).deleted_count > 0
