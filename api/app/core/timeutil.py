"""Dates in the organisation's time zone (all stored times are UTC)."""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def day_bounds_utc(day_from: date | None, day_to: date | None, tz_name: str) -> tuple[datetime | None, datetime | None]:
    """[start of day_from, start of the day after day_to) in the organisation's time zone, as UTC.

    "Visits on 25 September" means 25 September at the gate, not in UTC.
    """
    tz = ZoneInfo(tz_name)
    start = datetime.combine(day_from, time.min, tz).astimezone(UTC) if day_from else None
    end = datetime.combine(day_to + timedelta(days=1), time.min, tz).astimezone(UTC) if day_to else None
    return start, end


def local_year(moment: datetime, tz_name: str) -> int:
    return moment.astimezone(ZoneInfo(tz_name)).year
