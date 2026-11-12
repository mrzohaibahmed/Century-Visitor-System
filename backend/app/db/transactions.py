"""Transactions: app/db/sql/transactions.py (one SQL Server transaction, retried when chosen as a deadlock
victim)."""
from collections.abc import Awaitable, Callable

from app.db.sql.transactions import run_in_transaction as _transaction
from app.db.types import Db, DbSession


async def run_in_transaction[T](db: Db, work: Callable[[DbSession], Awaitable[T]]) -> T:
    """Runs `work(session)` in one transaction (all or nothing), retrying it on transient conflicts.
    Every read/write inside `work` must pass session=session."""
    return await _transaction(db, work)
