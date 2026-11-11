"""How a SQL Server repository function gets its connection."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb


@asynccontextmanager
async def connection(db: SqlDb, session: AsyncConnection | None = None) -> AsyncIterator[AsyncConnection]:
    """The caller's transaction (`session`, from run_in_transaction) if there is one; otherwise a new
    connection in its own transaction, committed when the block ends (rolled back on an error)."""
    if session is not None:
        yield session
        return
    async with db.engine.begin() as conn:
        yield conn
