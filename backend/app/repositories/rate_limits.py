"""Fixed-window counters in SQL Server (shared by all API workers).
Expired windows are left behind; a periodic clean-up deletes them (app/db/sql/cleanup.py)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert as sql_insert
from sqlalchemy import update

from app.db.errors import DuplicateKey
from app.db.sql.database import SqlDb
from app.repositories import tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error

rate_limits = tables.rate_limits


async def hit(db: SqlDb, key: str, window_minutes: int) -> int:
    """Counts one attempt for `key` in the current window and returns the total so far."""
    now = datetime.now(UTC)
    window_start = int(now.timestamp()) // (window_minutes * 60)
    window_key = f"{key}:{window_start}"
    expires_at = datetime.fromtimestamp((window_start + 1) * window_minutes * 60, UTC) + timedelta(minutes=1)
    for _ in range(2):   # two first attempts at the same moment: one insert loses, its retry then updates
        try:
            with duplicates_as_domain_error():
                async with connection(db) as conn:
                    count = (await conn.execute(
                        update(rate_limits).where(rate_limits.c.window_key == window_key)
                        .values(count=rate_limits.c.count + 1).returning(rate_limits.c.count))).scalar_one_or_none()
                    if count is None:
                        await conn.execute(sql_insert(rate_limits),
                                           {"window_key": window_key, "count": 1, "expires_at": expires_at})
                        count = 1
                    return int(count)
        except DuplicateKey:
            continue
    raise RuntimeError("rate limit counter could not be updated")
