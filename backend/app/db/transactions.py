"""Transactions, for the backend this process uses (CG_DB_BACKEND).

MongoDB: a multi-document transaction (the database must be a replica set), retried on transient errors
such as write conflicts. SQL Server: app/db/sql/transactions.py, retried when chosen as a deadlock victim."""
from collections.abc import Awaitable, Callable

from app.db.backend import BACKEND
from app.db.types import Db, DbSession


async def _mongo_transaction(db, work):
    async with db.client.start_session() as session:
        return await session.with_transaction(work)


if BACKEND == "mssql":
    from app.db.sql.transactions import run_in_transaction as _transaction
else:
    _transaction = _mongo_transaction


async def run_in_transaction[T](db: Db, work: Callable[[DbSession], Awaitable[T]]) -> T:
    """Runs `work(session)` in one transaction (all or nothing), retrying it on transient conflicts.
    Every read/write inside `work` must pass session=session."""
    return await _transaction(db, work)
