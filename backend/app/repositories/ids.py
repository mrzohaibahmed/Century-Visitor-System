"""Record IDs. Services treat IDs as opaque values and use these helpers instead of the driver's ID type."""
from bson import ObjectId


def parse_id(value: str | ObjectId | None) -> ObjectId | None:
    """The ID for `value`, or None if it is missing or not a valid ID (an ID passes through unchanged)."""
    if value is None or isinstance(value, ObjectId):
        return value
    return ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else None


def is_id(value: object) -> bool:
    return isinstance(value, ObjectId)
