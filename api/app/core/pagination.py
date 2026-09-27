"""Opaque cursors for keyset pagination (stable under inserts; no skip/offset scans)."""
import base64
import json
from datetime import datetime

from bson import ObjectId

from app.core.errors import AppError


def encode_cursor(sort_value: datetime | str, doc_id: ObjectId) -> str:
    value = sort_value.isoformat() if isinstance(sort_value, datetime) else sort_value
    raw = json.dumps({"v": value, "id": str(doc_id), "t": isinstance(sort_value, datetime)})
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime | str, ObjectId]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        value = datetime.fromisoformat(data["v"]) if data["t"] else str(data["v"])
        return value, ObjectId(data["id"])
    except Exception:  # noqa: BLE001 - any malformed cursor is the client's error
        raise AppError(400, "invalid_cursor", "The page link is not valid. Please search again.") from None
