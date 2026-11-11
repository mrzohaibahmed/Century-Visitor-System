"""What a visit list is narrowed to: the same for every backend (no database code here)."""
from dataclasses import dataclass
from datetime import datetime

from app.db.types import RecordId


@dataclass(frozen=True)
class VisitFilter:
    """What a visit list is narrowed to. Shared by the visit history (GET /visits) and the reports, so
    both filter the same way. Ids are already-validated record IDs; times are UTC (start included, end
    excluded), usually from day_bounds_utc() or timeutil.resolve_range()."""

    start: datetime | None = None
    end: datetime | None = None
    status: str | None = None
    host_id: RecordId | None = None
    department_id: RecordId | None = None
    gate_id: RecordId | None = None
    visitor_id: RecordId | None = None
    guard_id: RecordId | None = None        # the operator who checked the visit in OR out (reports)
    reason_code: str | None = None          # the purpose of the visit (reports)
    q: str | None = None                    # a visit number, or a visitor's name / ID number / phone
