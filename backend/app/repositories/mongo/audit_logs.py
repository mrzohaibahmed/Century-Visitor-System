"""MongoDB access for the append-only audit trail. Deliberately insert-only: no update or delete."""
from collections.abc import AsyncIterator

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase


async def insert(db: AsyncDatabase, entry: dict, session: AsyncClientSession | None = None) -> None:
    """Inserts the entry and sets entry["_id"]."""
    await db.audit_logs.insert_one(entry, session=session)


async def iter_by_action(db: AsyncDatabase, action: str) -> AsyncIterator[dict]:
    """Every entry with this action, oldest first (insertion order)."""
    async for entry in db.audit_logs.find({"action": action}).sort("_id", 1):
        yield entry
