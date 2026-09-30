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

__all__ = ["CountByDepartment", "CountByHour", "CountByStatus", "OverviewOut", "OverviewSeries", "OverviewTotals",
           "RangePreset", "ReportRangeOut", "ReportRef", "SeriesPoint", "VisitReportPage", "VisitReportRow",
           "VisitReportSort"]


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
