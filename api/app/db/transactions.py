"""Multi-document transactions (the database must be a replica set)."""
from collections.abc import Awaitable, Callable

from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase


async def run_in_transaction[T](db: AsyncDatabase, work: Callable[[AsyncClientSession], Awaitable[T]]) -> T:
    """Runs `work(session)` in a transaction, retrying on transient errors (e.g. write conflicts).
    Every read/write inside `work` must pass session=session."""
    async with db.client.start_session() as session:
        return await session.with_transaction(work)
