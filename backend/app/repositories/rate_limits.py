"""Fixed-window counters in MongoDB (shared by all API workers; expired by a TTL index)."""
from datetime import UTC, datetime, timedelta

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError


async def hit(db: AsyncDatabase, key: str, window_minutes: int) -> int:
    """Counts one attempt for `key` in the current window and returns the total so far."""
    now = datetime.now(UTC)
    window_start = int(now.timestamp()) // (window_minutes * 60)
    doc_id = f"{key}:{window_start}"
    expires_at = datetime.fromtimestamp((window_start + 1) * window_minutes * 60, UTC) + timedelta(minutes=1)
    for _ in range(2):   # an upsert race between two requests can raise once; the retry then finds the doc
        try:
            doc = await db.rate_limits.find_one_and_update(
                {"_id": doc_id},
                {"$inc": {"count": 1}, "$setOnInsert": {"expires_at": expires_at}},
                upsert=True, return_document=ReturnDocument.AFTER)
            return int(doc["count"])
        except DuplicateKeyError:
            continue
    raise RuntimeError("rate limit counter could not be updated")
