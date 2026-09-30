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


INVALID_CURSOR = AppError(400, "invalid_cursor", "The page link is not valid. Please search again.")


def encode_sort_cursor(sort: str, value: datetime | int | None, doc_id: ObjectId,
                       as_of: datetime | None = None) -> str:
    """A keyset cursor for lists with several sort orders (reports). It names its sort order, so a cursor
    from one order is refused under another. `value` may be None (e.g. no check-out time yet); `as_of`
    pins "now" for orders computed from it (the duration of a visit still inside), so every page of one
    list uses the same moment."""
    kind = "d" if isinstance(value, datetime) else "i" if isinstance(value, int) else "n"
    raw = {"s": sort, "k": kind, "v": value.isoformat() if kind == "d" else value, "id": str(doc_id)}
    if as_of is not None:
        raw["n"] = as_of.isoformat()
    return base64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("=")


def decode_sort_cursor(cursor: str, sort: str) -> tuple[datetime | int | None, ObjectId, datetime | None]:
    """(value, id, as_of). Any malformed cursor, or one made for another sort order, is refused."""
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if data["s"] != sort:
            raise ValueError("sort mismatch")
        kind, raw = data["k"], data["v"]
        if kind == "d":
            value = datetime.fromisoformat(raw)
        elif kind == "i" and type(raw) is int:
            value = raw
        elif kind == "n" and raw is None:
            value = None
        else:
            raise ValueError("bad value")
        as_of = datetime.fromisoformat(data["n"]) if data.get("n") else None
        if any(d is not None and d.tzinfo is None for d in (value if kind == "d" else None, as_of)):
            raise ValueError("naive datetime")
        return value, ObjectId(data["id"]), as_of
    except Exception:  # noqa: BLE001 - any malformed cursor is the client's error
        raise INVALID_CURSOR from None


def decode_cursor(cursor: str) -> tuple[datetime | str, ObjectId]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        value = datetime.fromisoformat(data["v"]) if data["t"] else str(data["v"])
        return value, ObjectId(data["id"])
    except Exception:  # noqa: BLE001 - any malformed cursor is the client's error
        raise AppError(400, "invalid_cursor", "The page link is not valid. Please search again.") from None
