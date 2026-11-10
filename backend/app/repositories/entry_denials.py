"""MongoDB access for refused entries (reporting only; never part of the security decision)."""
from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.repositories.errors import duplicates_as_domain_error


async def insert(db: AsyncDatabase, doc: dict) -> None:
    """Raises DuplicateKey if this source audit entry is already recorded. Other database errors are
    raised unchanged (see errors.DATABASE_ERRORS)."""
    with duplicates_as_domain_error():
        await db.entry_denials.insert_one(doc)


async def insert_if_absent(db: AsyncDatabase, source_audit_id: ObjectId, doc: dict) -> bool:
    """Creates the document for this audit entry unless one exists (an existing one is never changed).
    True if it was created. Raises DuplicateKey when a concurrent run created it at the same moment."""
    with duplicates_as_domain_error():
        result = await db.entry_denials.update_one(
            {"source_audit_id": source_audit_id}, {"$setOnInsert": doc}, upsert=True)
    return result.upserted_id is not None
