"""
The SQL Server database for the app's lifetime (app.db.client.Database).

- SqlDatabase: created in the FastAPI lifespan; owns the connection pool; answers /health/ready.
- SqlDb:       what repositories receive as `db` (app.db.types.Db): just the pool, nothing to manage.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import LEGACY_DATABASE_NAMES, Settings
from app.db.sql.engine import async_engine
from app.db.sql.revision import current_revision, schema_status


class SqlDb:
    """The handle SQL Server repositories get: they open connections (or join the caller's transaction)."""

    def __init__(self, engine: AsyncEngine, name: str):
        self.engine = engine
        self.name = name


class SqlDatabase:
    def __init__(self, settings: Settings):
        if settings.mssql_database.lower() in LEGACY_DATABASE_NAMES:      # defence in depth; Settings refuses
            raise RuntimeError("Refusing to connect to the legacy desktop database.")
        self.name = settings.mssql_database
        self.engine = async_engine(settings)
        self.db = SqlDb(self.engine, self.name)

    async def ping(self) -> None:
        """Raises one of repositories.errors.DATABASE_ERRORS if the database cannot be reached."""
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def transactions_available(self) -> bool:
        return True                                    # always on SQL Server

    async def schema_status(self) -> str:
        """ok, missing (never migrated) or outdated."""
        async with self.engine.connect() as conn:
            return schema_status(await conn.run_sync(current_revision))

    async def close(self) -> None:
        await self.engine.dispose()
