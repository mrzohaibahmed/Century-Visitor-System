"""
Free-form values (audit changes / metadata, notification data) stored as JSON in SQL Server.

IDs and times inside keep their type through a small tag ({"$id": ...}, {"$date": ...}), so a reader gets
back exactly what was written. Times are cut to milliseconds, like every stored time (repositories/types.py).
"""
import json
import uuid
from datetime import datetime


def _tagged(value):
    if isinstance(value, uuid.UUID):
        return {"$id": str(value)}
    if isinstance(value, datetime):
        return {"$date": value.replace(microsecond=value.microsecond // 1000 * 1000).isoformat()}
    if isinstance(value, dict):
        return {str(k): _tagged(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_tagged(v) for v in value]
    return value


def _untagged(obj: dict):
    if len(obj) == 1 and "$id" in obj:
        return uuid.UUID(obj["$id"])
    if len(obj) == 1 and "$date" in obj:
        return datetime.fromisoformat(obj["$date"])
    return obj


def to_json(value) -> str | None:
    return None if value is None else json.dumps(_tagged(value), ensure_ascii=False, separators=(",", ":"))


def from_json(text: str | None):
    return None if text is None else json.loads(text, object_hook=_untagged)
