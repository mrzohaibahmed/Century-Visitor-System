"""Column types that make SQL Server values behave like the MongoDB ones the services already expect."""
from datetime import UTC, datetime

from sqlalchemy.dialects.mssql import DATETIME2
from sqlalchemy.types import TypeDecorator


class UtcDateTime(TypeDecorator):
    """DATETIME2(3) holding UTC. Python side: timezone-aware datetimes only.

    - writing (and comparing): the value is converted to UTC and cut to whole milliseconds, exactly as
      MongoDB stores a datetime (so stored values, cursors and comparisons behave as before);
    - reading: the value comes back as an aware UTC datetime (MongoDB's tz_aware=True).
    A naive datetime is refused: it would be ambiguous (local time or UTC?).
    """

    impl = DATETIME2(precision=3)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"UtcDateTime expects a datetime, not {type(value).__name__}")
        if value.tzinfo is None:
            raise ValueError("UtcDateTime refuses a naive datetime: pass an aware (UTC) one")
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None, microsecond=value.microsecond // 1000 * 1000)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None
