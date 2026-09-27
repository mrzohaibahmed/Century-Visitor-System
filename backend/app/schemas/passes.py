"""Visitor passes (QR on the badge), badge contents and QR check-out."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from app.schemas.common import StrictModel
from app.schemas.visits import VisitOut


class ScannedPass(StrictModel):
    """Text read from the QR code (camera or USB scanner). Sent in the body, never in a URL,
    so it does not end up in proxy or browser history logs."""
    qr_text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class BadgeOut(BaseModel):
    """Only what the gate needs on a worn badge: no ID number, phone or address."""
    organization: str
    visitor_name: str
    visit_number: str
    host_name: str | None
    department_name: str | None
    gate_name: str | None
    check_in_at: datetime
    valid_until: datetime

    @classmethod
    def from_visit(cls, visit: dict, organization: str, valid_until: datetime) -> "BadgeOut":
        snap = visit.get("snapshot", {})
        return cls(organization=organization, visitor_name=snap["visitor_name"], visit_number=visit["visit_number"],
                   host_name=snap.get("host_name"), department_name=snap.get("department_name"),
                   gate_name=snap.get("gate_name"), check_in_at=visit["check_in_at"], valid_until=valid_until)


class IssuedPassOut(BaseModel):
    """Returned once, to print the badge. The token is not stored anywhere in readable form;
    printing again means issuing a new pass (which cancels this one)."""
    qr_text: str
    expires_at: datetime
    badge: BadgeOut


class ScanOut(BaseModel):
    """What a scanned pass refers to. VALID: the visitor is inside and may be checked out."""
    status: Literal["VALID", "CHECKED_OUT"]
    visit: VisitOut
