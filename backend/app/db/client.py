"""MongoDB connection (PyMongo's native async API; Motor is deprecated)."""
import logging

from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import LEGACY_DATABASE_NAMES, Settings

log = logging.getLogger(__name__)


class Database:
    """Owns the client for the application's lifetime (created in the FastAPI lifespan)."""

    def __init__(self, settings: Settings):
        if settings.mongo_db.lower() in LEGACY_DATABASE_NAMES:          # defence in depth; Settings already refuses
            raise RuntimeError("Refusing to connect to the legacy desktop database.")
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

    async def close(self) -> None:
        await self.client.close()
