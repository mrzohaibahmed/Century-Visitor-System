"""Visits (one entry into the premises)."""
import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator, model_validator

from app.core.identity import normalize_name
from app.schemas.common import IdStr, StrictModel
from app.schemas.visitors import IdentityIn


class VisitReason(StrEnum):
    OFFICIAL_MEETING = "OFFICIAL_MEETING"
    INTERVIEW = "INTERVIEW"
    DELIVERY = "DELIVERY"
    MAINTENANCE = "MAINTENANCE"
    CONTRACTOR_WORK = "CONTRACTOR_WORK"
    PERSONAL = "PERSONAL"
    OTHER = "OTHER"


class VisitStatus(StrEnum):
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


# V-26-OCT-02-001: year, month and day at the gate, then that day's count. Visits numbered in the
# earlier formats (V-26-0210-001, V-2026-000123) keep them and can still be looked up and checked out.
VISIT_NUMBER = re.compile(r"^V-(\d{2}-[A-Z]{3}-\d{2}-\d{3,}|\d{2}-\d{4}-\d{3,}|\d{4}-\d{6,})$")
Belonging = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)]


class CheckInRequest(StrictModel):
    visitor_id: IdStr
    host_id: IdStr | None = None
    # Only when the host is not in the directory; the visit is then flagged for review.
    unlisted_host_name: str | None = None
    department_id: IdStr | None = None
    reason_code: VisitReason
    reason_note: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    vehicle_registration: str | None = None
    belongings: list[Belonging] = Field(default_factory=list, max_length=10)
    # The visitor's current photo, captured just before (POST /visitors/{id}/photo). Optional:
    # a gate without a working camera can still check visitors in.
    photo_id: IdStr | None = None

    @field_validator("unlisted_host_name")
    @classmethod
    def _host_name(cls, v):
        return normalize_name(v) if v else None

    @field_validator("vehicle_registration")
    @classmethod
    def _vehicle(cls, v):
        if not v or not v.strip():
            return None
        compact = re.sub(r"\s+", "", v).upper()
        if not re.fullmatch(r"[A-Z0-9-]{2,15}", compact):
            raise ValueError("The vehicle registration may only contain letters, digits and hyphens (2–15).")
        return compact

    @model_validator(mode="after")
    def _rules(self):
        if bool(self.host_id) == bool(self.unlisted_host_name):
            raise ValueError("Choose a host from the directory, or enter the name of a host who is not listed.")
        if self.reason_code is VisitReason.OTHER and not self.reason_note:
            raise ValueError("Describe the reason when 'Other' is selected.")
        return self


class UpdateBelongingsRequest(StrictModel):
    """Update personal material recorded on an active visit (gate forgot items at check-in, or corrected them)."""
    belongings: list[Belonging] = Field(default_factory=list, max_length=10)
    vehicle_registration: str | None = None

    @field_validator("vehicle_registration")
    @classmethod
    def _vehicle(cls, v):
        if not v or not v.strip():
            return None
        compact = re.sub(r"\s+", "", v).upper()
        if not re.fullmatch(r"[A-Z0-9-]{2,15}", compact):
            raise ValueError("The vehicle registration may only contain letters, digits and hyphens (2–15).")
        return compact


class CheckOutLookup(StrictModel):
    """Check-out by typed / scanned value: the visit number or the visitor's ID."""
    visit_number: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True)] | None = None
    identity: IdentityIn | None = None

    @model_validator(mode="after")
    def _one(self):
        if bool(self.visit_number) == bool(self.identity):
            raise ValueError("Give either a visit number or an ID number.")
        if self.visit_number and not VISIT_NUMBER.match(self.visit_number):
            raise ValueError("A visit number looks like V-26-OCT-02-001.")
        return self


class PersonRef(BaseModel):
    id: str | None
    name: str | None


class VisitOut(BaseModel):
    id: str
    visit_number: str
    status: str
    visitor: PersonRef
    host: PersonRef
    host_unlisted: bool
    department: PersonRef
    gate: PersonRef
    checkout_gate: PersonRef | None
    reason_code: str
    reason_note: str | None
    vehicle_registration: str | None
    belongings: list[str]
    check_in_at: datetime
    check_out_at: datetime | None
    checked_in_by: PersonRef
    checked_out_by: PersonRef | None
    checkout_method: str | None
    photo_id: str | None = None

    @classmethod
    def from_doc(cls, d: dict) -> "VisitOut":
        snap = d.get("snapshot", {})

        def ref(id_field: str, name_field: str) -> PersonRef:
            value = d.get(id_field)
            return PersonRef(id=str(value) if value else None, name=snap.get(name_field))

        out = d.get("checked_out_by")
        return cls(
            id=str(d["_id"]), visit_number=d["visit_number"], status=d["status"],
            visitor=ref("visitor_id", "visitor_name"), host=ref("host_id", "host_name"),
            host_unlisted=d.get("host_unlisted", False), department=ref("department_id", "department_name"),
            gate=ref("gate_id", "gate_name"),
            checkout_gate=ref("checkout_gate_id", "checkout_gate_name") if d.get("checkout_gate_id") else None,
            reason_code=d["reason_code"], reason_note=d.get("reason_note"),
            vehicle_registration=d.get("vehicle_registration"), belongings=d.get("belongings", []),
            check_in_at=d["check_in_at"], check_out_at=d.get("check_out_at"),
            checked_in_by=ref("checked_in_by", "checked_in_by_name"),
            checked_out_by=PersonRef(id=str(out), name=snap.get("checked_out_by_name")) if out else None,
            checkout_method=d.get("checkout_method"),
            photo_id=str(d["photo_id"]) if d.get("photo_id") else None,
        )


class CheckOutResult(BaseModel):
    visit: VisitOut
    already_checked_out: bool


class ActiveVisits(BaseModel):
    items: list[VisitOut]
    total: int
