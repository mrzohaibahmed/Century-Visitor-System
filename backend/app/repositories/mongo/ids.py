"""MongoDB record IDs (ObjectId). Everything outside the repositories treats IDs as opaque values
(app.db.types.RecordId) and uses these helpers, through app/repositories/ids.py."""
from bson import ObjectId


def parse_id(value: str | ObjectId | None) -> ObjectId | None:
    """The ID for `value`, or None if it is missing or not a valid ID (an ID passes through unchanged)."""
    if value is None or isinstance(value, ObjectId):
        return value
    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else None


def to_id(value: str) -> ObjectId:
    """The ID for a string that must be one (e.g. inside a page cursor). Raises ValueError otherwise."""
    record_id = parse_id(value) if isinstance(value, str) else None
    if record_id is None:
        raise ValueError("not a record id")
    return record_id


def is_id(value: object) -> bool:
    return isinstance(value, ObjectId)
