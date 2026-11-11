"""The database for the app's lifetime: open_database() picks the backend this process uses (CG_DB_BACKEND).

MongoDB: Database below (PyMongo's native async API; Motor is deprecated).
SQL Server: app/db/sql/database.py (SqlDatabase), with the same methods.
"""
import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import LEGACY_DATABASE_NAMES, Settings
from app.db.backend import BACKEND
from app.db.migrate import current_schema_version
from app.db.schema import SCHEMA_VERSION

log = logging.getLogger(__name__)


def open_database(settings: Settings):
    """The database object of the configured backend (Database or SqlDatabase); created in the lifespan."""
    if BACKEND == "mssql":
        from app.db.sql.database import SqlDatabase
        return SqlDatabase(settings)
    return Database(settings)


class Database:
    """Owns the client for the application's lifetime (created in the FastAPI lifespan)."""

    def __init__(self, settings: Settings):
        if settings.mongo_db.lower() in LEGACY_DATABASE_NAMES:          # defence in depth; Settings already refuses
            raise RuntimeError("Refusing to connect to the legacy desktop database.")
        self.name = settings.mongo_db
        self.client: AsyncMongoClient = AsyncMongoClient(
            settings.mongo_uri.get_secret_value(),
            serverSelectionTimeoutMS=settings.mongo_timeout_ms,
            connectTimeoutMS=settings.mongo_timeout_ms,
            tz_aware=True,                      # datetimes come back as aware UTC
            uuidRepresentation="standard",
            appname="century-gate-vms-api",
        )
        self.db: AsyncDatabase = self.client[settings.mongo_db]

    async def ping(self) -> None:
        """Raises one of repositories.errors.DATABASE_ERRORS if the database cannot be reached."""
        await self.db.command("ping")

    async def transactions_available(self) -> bool:
        """Multi-document transactions need a replica set (or a sharded cluster)."""
        hello = await self.db.command("hello")
        return bool(hello.get("setName") or hello.get("msg") == "isdbgrid")

    async def schema_status(self) -> str:
        """ok, missing (never migrated) or outdated, for /health/ready."""
        version = await current_schema_version(self.db)
        return "ok" if version == SCHEMA_VERSION else "missing" if version is None else "outdated"

    async def close(self) -> None:
        await self.client.close()
