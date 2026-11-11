"""
Deletes expired sessions and login rate-limit windows on SQL Server (CG_DB_BACKEND=mssql).

MongoDB removed them itself (TTL indexes on expires_at); SQL Server has no TTL, so the API does it in the
background. Only rows whose expires_at has passed go, exactly what the TTL indexes removed: a session is
never deleted before its absolute expiry, whatever happened to it, so audit and "session expired" answers
are unchanged. The first pass waits a full interval after start-up.
"""
import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import delete

from app.db.sql.database import SqlDb
from app.db.sql.errors import describe_error
from app.repositories.mssql import tables

log = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


async def delete_expired(db: SqlDb, now: datetime | None = None) -> dict[str, int]:
    """Deletes sessions and rate-limit windows that expired before `now`; returns how many of each."""
    now = now or datetime.now(UTC)
    async with db.engine.begin() as conn:
        sessions = (await conn.execute(delete(tables.sessions).where(tables.sessions.c.expires_at < now))).rowcount
        windows = (await conn.execute(delete(tables.rate_limits).where(tables.rate_limits.c.expires_at < now))
                   ).rowcount
    return {"sessions": sessions, "rate_limits": windows}


class CleanupWorker:
    """Runs delete_expired() every INTERVAL_SECONDS inside the API process (first after one interval)."""

    def __init__(self, db: SqlDb, interval_seconds: int = INTERVAL_SECONDS):
        self._db = db
        self._interval = interval_seconds

    async def run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                removed = await delete_expired(self._db)
                if any(removed.values()):
                    log.info("Expired rows deleted (sessions %d, rate-limit windows %d)",
                             removed["sessions"], removed["rate_limits"])
            except asyncio.CancelledError:
                raise
            except Exception as e:                   # noqa: BLE001 - e.g. the database briefly unreachable
                log.warning("Expired-row clean-up failed (%s); retrying in %d s", describe_error(e), self._interval)
