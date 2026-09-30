"""
Reports (administrators only: reports:view; exports also need reports:export).

Report rows never carry a full ID number or phone number, for any role: both are masked with
core.identity.mask_sensitive(). The full values stay in the visitor details view, which has its own
permission and audit trail. Report rows never carry photos, QR pass data or belongings either.
"""
from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from app.core.identity import mask_sensitive
from app.core.timeutil import DayRange, RangePreset
from app.db.schema import DENIAL_SOURCES

__all__ = ["CountByDepartment", "CountByHour", "CountByStatus", "DenialPage", "DenialRow", "DenialSource",
           "DepartmentPage", "DepartmentRow", "GuardPage", "GuardRow", "HostPage", "HostRow", "InsidePage",
           "InsideSort", "OverviewOut", "OverviewSeries", "OverviewTotals", "RangePreset", "ReportRangeOut",
           "ReportRef", "SeriesPoint",
           "VisitReportPage", "VisitReportRow", "VisitReportSort", "VisitorSummaryPage", "VisitorSummaryRow",
           "VisitorSummarySort"]


class VisitReportSort(StrEnum):
    CHECK_IN_DESC = "check_in_desc"          # newest first (default, like the visit history)
    CHECK_IN_ASC = "check_in_asc"
    CHECK_OUT_DESC = "check_out_desc"
    DURATION_DESC = "duration_desc"


class ReportRangeOut(BaseModel):
    """The local days a report covers, both included (serialised as "from" / "to")."""

    preset: RangePreset
    date_from: date = Field(serialization_alias="from")
    date_to: date = Field(serialization_alias="to")
    timezone: str

    @classmethod
    def from_range(cls, r: DayRange) -> "ReportRangeOut":
        return cls(preset=r.preset, date_from=r.first_day, date_to=r.last_day, timezone=r.tz_name)


class ReportRef(BaseModel):
    id: str | None
    name: str | None


def duration_minutes(check_in_at: datetime, check_out_at: datetime | None, now: datetime) -> int:
    """Whole minutes on site: until check-out, or until now for a visitor still inside."""
    return max(0, int(((check_out_at or now) - check_in_at).total_seconds() // 60))


class VisitReportRow(BaseModel):
    id: str
    visit_number: str
    visitor: ReportRef
    id_type: str | None
    id_number: str | None              # masked
    phone: str | None                  # masked
    host: ReportRef
    host_unlisted: bool
    department: ReportRef
    reason_code: str
    reason_note: str | None
    gate: ReportRef
    check_in_at: datetime
    check_out_at: datetime | None
    duration_minutes: int
    status: str
    checked_in_by: ReportRef
    checked_out_by: ReportRef | None

    @classmethod
    def from_doc(cls, d: dict, visitor: dict | None, now: datetime) -> "VisitReportRow":
        """`visitor`: the visitor's identity and phone, from one batched lookup per page (may be None)."""
        snap = d.get("snapshot", {})

        def ref(id_field: str, name_field: str) -> ReportRef:
            value = d.get(id_field)
            return ReportRef(id=str(value) if value else None, name=snap.get(name_field))

        ident = (visitor or {}).get("identity") or {}
        out = d.get("checked_out_by")
        return cls(
            id=str(d["_id"]), visit_number=d["visit_number"], visitor=ref("visitor_id", "visitor_name"),
            id_type=ident.get("type"), id_number=mask_sensitive(ident.get("number")),
            phone=mask_sensitive((visitor or {}).get("phone")),
            host=ref("host_id", "host_name"), host_unlisted=d.get("host_unlisted", False),
            department=ref("department_id", "department_name"),
            reason_code=d["reason_code"], reason_note=d.get("reason_note"), gate=ref("gate_id", "gate_name"),
            check_in_at=d["check_in_at"], check_out_at=d.get("check_out_at"),
            duration_minutes=duration_minutes(d["check_in_at"], d.get("check_out_at"), now),
            status=d["status"], checked_in_by=ref("checked_in_by", "checked_in_by_name"),
            checked_out_by=ReportRef(id=str(out), name=snap.get("checked_out_by_name")) if out else None,
        )


class VisitReportPage(BaseModel):
    range: ReportRangeOut               # the local days actually covered (presets resolved on the server)
    items: list[VisitReportRow]
    total: int                          # all rows matching the filters (for "1–25 of 1,240")
    next_cursor: str | None = None


# ------------------------------------------------------------------------------------------ overview
class OverviewTotals(BaseModel):
    """Everything here is about visits that CHECKED IN within the range, except `inside_now`."""

    visits: int
    unique_visitors: int
    inside_now: int = Field(description="Current state: visitors inside right now, whatever the range.")
    checked_out: int                    # visits of the range that have since checked out
    denied_entries: int                 # entries refused at the gate within the range (watchlist)
    watchlist_matches: int              # watchlist hits at check-in within the range
    avg_duration_minutes: int | None = Field(
        description="Average of completed visits only (check-out minus check-in); visits still inside are "
                    "left out. None when no visit of the range has checked out.")


class SeriesPoint(BaseModel):
    start: datetime                     # start of the hour or day, in the organisation's time zone
    count: int


class CountByDepartment(BaseModel):
    id: str | None
    name: str | None
    count: int


class CountByStatus(BaseModel):
    status: str
    count: int


class CountByHour(BaseModel):
    hour: int                           # 0-23, local time
    count: int


class OverviewSeries(BaseModel):
    bucket: Literal["hour", "day"]      # hours for a one-day range, days otherwise
    over_time: list[SeriesPoint]        # every bucket of the range, zeros included
    by_department: list[CountByDepartment]
    by_status: list[CountByStatus]      # every status, zeros included
    peak_hours: list[CountByHour]       # all 24 hours, zeros included


class OverviewOut(BaseModel):
    range: ReportRangeOut
    generated_at: datetime
    totals: OverviewTotals
    series: OverviewSeries


# ------------------------------------------------------------------------------------------ visitor summary
class VisitorSummarySort(StrEnum):
    LAST_VISIT_DESC = "last_visit_desc"      # most recent visitor first (default)
    VISITS_DESC = "visits_desc"              # most frequent visitor first


class VisitorSummaryRow(BaseModel):
    """One visitor's visits that CHECKED IN within the range; `inside_now` is the current state."""

    visitor: ReportRef
    id_type: str | None
    id_number: str | None              # masked
    phone: str | None                  # masked
    visits: int
    completed_visits: int
    first_visit_at: datetime           # within the range
    last_visit_at: datetime            # within the range
    avg_duration_minutes: int | None   # completed visits only; None if none completed
    inside_now: bool

    @classmethod
    def from_group(cls, g: dict, visitor: dict | None, inside_now: bool) -> "VisitorSummaryRow":
        ident = (visitor or {}).get("identity") or {}
        return cls(
            visitor=ReportRef(id=str(g["_id"]), name=(visitor or {}).get("full_name") or g.get("name")),
            id_type=ident.get("type"), id_number=mask_sensitive(ident.get("number")),
            phone=mask_sensitive((visitor or {}).get("phone")), visits=g["visits"],
            completed_visits=g["completed"], first_visit_at=g["first"], last_visit_at=g["last"],
            avg_duration_minutes=round(g["avg_ms"] / 60000) if g.get("avg_ms") is not None else None,
            inside_now=inside_now)


class VisitorSummaryPage(BaseModel):
    range: ReportRangeOut
    items: list[VisitorSummaryRow]
    total: int                          # visitors with at least one visit matching the filters
    next_cursor: str | None = None


# ------------------------------------------------------------------------------------------ hosts, departments
class HostRow(BaseModel):
    """A host visited within the range, per department recorded on the visits. An unlisted host (typed in
    at the gate) has no id and is identified by the name typed."""

    host: ReportRef
    host_unlisted: bool
    department: ReportRef
    visits: int
    completed_visits: int
    inside_now: int = Field(description="Current state: this host's visitors inside right now, whatever the range.")


class HostPage(BaseModel):
    range: ReportRangeOut
    items: list[HostRow]               # most visited first
    total: int                          # rows before the limit
    truncated: bool


class DepartmentRow(BaseModel):
    department: ReportRef
    visits: int
    completed_visits: int
    unique_visitors: int
    avg_duration_minutes: int | None   # completed visits only
    inside_now: int = Field(description="Current state: visitors inside right now, whatever the range.")


class DepartmentPage(BaseModel):
    range: ReportRangeOut
    items: list[DepartmentRow]
    total: int
    truncated: bool


# ------------------------------------------------------------------------------------------ guards
class GuardRef(BaseModel):
    id: str | None                      # None: refusals whose operator was never recorded (old backfill)
    name: str | None
    role: str | None
    is_active: bool | None


class GuardRow(BaseModel):
    """What one operator handled within the range. Operators come from the visits' checked_in_by /
    checked_out_by and the denials' operator_id, all written from the session at the time."""

    guard: GuardRef
    check_ins: int                      # visits checked in within the range
    check_outs: int                     # visits checked out within the range (by check-out time)
    inside_now: int = Field(description="Current state: visitors this operator checked in who are inside now.")
    denied_entries: int                 # refusals within the range
    watchlist_matches: int              # of those, refusals for the watchlist


class GuardPage(BaseModel):
    range: ReportRangeOut
    items: list[GuardRow]
    total: int
    truncated: bool


# ------------------------------------------------------------------------------------------ currently inside
class InsideSort(StrEnum):
    CHECK_IN_ASC = "check_in_asc"            # longest inside first (default)
    CHECK_IN_DESC = "check_in_desc"          # most recent arrivals first


class InsidePage(BaseModel):
    """Current state: every visit still checked in, whenever it started (no date range)."""

    generated_at: datetime              # the moment the durations are measured to
    items: list[VisitReportRow]
    total: int
    next_cursor: str | None = None


# ------------------------------------------------------------------------------------------ denials
DenialSource = StrEnum("DenialSource", {s.upper(): s for s in DENIAL_SOURCES})     # as in the collection


class WatchlistRef(BaseModel):
    id: str | None
    reason: str | None                  # the watchlist entry's reason as it is now


class DenialRow(BaseModel):
    """One refused entry (entry_denials). Names are those recorded at the time; for older rebuilt records
    (source audit_backfill) missing names are filled from the current records and listed in
    `current_names`."""

    id: str
    at: datetime
    reason: str
    reason_code: str | None
    source: str
    visitor: ReportRef
    identifier: str | None              # masked when recorded
    watchlist: WatchlistRef
    gate: ReportRef
    operator: ReportRef
    current_names: list[Literal["visitor", "gate", "operator"]]


class DenialPage(BaseModel):
    range: ReportRangeOut
    denied_entries: int                 # the whole range, as in the overview
    watchlist_matches: int              # the whole range, as in the overview
    total: int                          # rows matching the filters
    items: list[DenialRow]
    next_cursor: str | None = None
