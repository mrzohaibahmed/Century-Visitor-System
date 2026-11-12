"""SQL Server transactions: `work(connection)` runs in one transaction, retried if chosen as a deadlock victim.
Everything inside `work` must use that connection (passed on as session=)."""
import asyncio
import random
from collections.abc import Awaitable, Callable

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.db.sql.errors import is_deadlock

MAX_ATTEMPTS = 5


async def run_in_transaction[T](db: SqlDb, work: Callable[[AsyncConnection], Awaitable[T]]) -> T:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            async with db.engine.begin() as connection:        # commits on success, rolls back on any error
                return await work(connection)
        except DBAPIError as e:
            if attempt < MAX_ATTEMPTS and is_deadlock(e):
                await asyncio.sleep(random.uniform(0.01, 0.05) * attempt)   # noqa: S311 - jitter, not security
                continue
            raise
    raise AssertionError("unreachable")
