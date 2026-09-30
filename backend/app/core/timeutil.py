"""Dates in the organisation's time zone (all stored times are UTC)."""
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

MAX_RANGE_DAYS = 366          # longest custom report range: a full (leap) year


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


def local_today(tz_name: str, now: datetime | None = None) -> date:
    """Today's date at the gate (not in UTC): 00:30 in Karachi is already the next day."""
    return (now or datetime.now(UTC)).astimezone(ZoneInfo(tz_name)).date()


# ------------------------------------------------------------------------------------------ report ranges
class RangePreset(StrEnum):
    TODAY = "today"
    YESTERDAY = "yesterday"
    THIS_WEEK = "this_week"           # Monday to today
    THIS_MONTH = "this_month"         # the 1st to today
    CUSTOM = "custom"                 # from and to, both included


class InvalidRange(ValueError):
    """A report range that cannot be used. The message is safe to show to the user."""


@dataclass(frozen=True)
class DayRange:
    """Whole local days, first_day to last_day included, and the same period in UTC for queries:
    start <= check_in_at < end."""

    preset: RangePreset
    first_day: date
    last_day: date
    start: datetime
    end: datetime
    tz_name: str

    @property
    def days(self) -> int:
        return (self.last_day - self.first_day).days + 1


def resolve_range(preset: RangePreset | str, day_from: date | None, day_to: date | None, tz_name: str, *,
                  now: datetime | None = None) -> DayRange:
    """The local days a report covers. Presets are worked out on the server, in the organisation's time
    zone, so a browser's clock or time zone never changes what "today" means. Raises InvalidRange."""
    try:
        preset = RangePreset(preset)
    except ValueError:
        raise InvalidRange("Choose a date range: today, yesterday, this week, this month or custom.") from None
    today = local_today(tz_name, now)
    if preset is RangePreset.CUSTOM:
        if day_from is None or day_to is None:
            raise InvalidRange("Choose both a start date and an end date.")
        if day_from > day_to:
            raise InvalidRange("The start date is after the end date.")
        if (day_to - day_from).days + 1 > MAX_RANGE_DAYS:
            raise InvalidRange(f"Choose a range of at most {MAX_RANGE_DAYS} days.")
        first, last = day_from, day_to
    else:
        if day_from is not None or day_to is not None:
            raise InvalidRange("Start and end dates are only used with a custom range.")
        first, last = {
            RangePreset.TODAY: (today, today),
            RangePreset.YESTERDAY: (today - timedelta(days=1), today - timedelta(days=1)),
            RangePreset.THIS_WEEK: (today - timedelta(days=today.weekday()), today),
            RangePreset.THIS_MONTH: (today.replace(day=1), today),
        }[preset]
    start, end = day_bounds_utc(first, last, tz_name)
    return DayRange(preset=preset, first_day=first, last_day=last, start=start, end=end, tz_name=tz_name)
