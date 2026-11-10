"""MongoDB access for the append-only audit trail. Deliberately insert-only: no update or delete."""
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase


async def insert(db: AsyncDatabase, entry: dict, session: AsyncClientSession | None = None) -> None:
    """Inserts the entry and sets entry["_id"]."""
    await db.audit_logs.insert_one(entry, session=session)
