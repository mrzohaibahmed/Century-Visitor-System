"""The results the report repositories return: the same for every backend (no database code here)."""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OverviewCounts:
    visits: int
    checked_out: int
    avg_ms: float | None                       # completed visits only
    unique_visitors: int
    by_status: dict[str, int]
    by_department: list[dict]                  # {"id", "name" (latest recorded on a visit), "count"}
    peak_hours: dict[int, int]                 # local hour -> visits
    over_time: dict[datetime, int]             # bucket start (UTC) -> visits


@dataclass(frozen=True)
class GuardGroups:
    check_ins: list[dict]      # {"operator", "n"}: checked in within the range (by check-in time)
    check_outs: list[dict]     # {"operator", "n"}: checked out within the range (by check-out time)
    inside: list[dict]         # {"operator", "n"}: visitors they checked in who are inside now
    denials: list[dict]        # {"operator", "n", "watchlist", "name"}: refusals within the range
