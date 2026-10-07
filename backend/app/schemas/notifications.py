"""In-app notifications (Phase 6A). The recipient only ever sees their own."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EmailStatus = Literal["NONE", "PENDING", "SENDING", "SENT", "FAILED"]


class ArrivalOut(BaseModel):
    visitor_name: str
    host_name: str | None
    gate_name: str | None
    department_name: str | None
    check_in_at: datetime


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    message: str
    created_at: datetime
    read: bool
    read_at: datetime | None
    arrival: ArrivalOut
    email_status: EmailStatus          # whether the host was also e-mailed (NONE: no address / e-mail off)

    @classmethod
    def from_doc(cls, d: dict) -> "NotificationOut":
        data = d["data"]
        overstay = d["type"] in ("HOST_VISITOR_OVERSTAY", "DEPARTMENT_VISITOR_OVERSTAY")
        if overstay:
            title, message = "Visitor overstay", (
                f"{data['visitor_name']} is still on site after their badge expired.")
        else:
            title, message = "Visitor arrived", (
                f"{data['visitor_name']} has arrived to visit {data.get('host_name') or 'you'}.")
        return cls(
            id=str(d["_id"]), type=d["type"], title=title, message=message,
            created_at=d["created_at"], read=d.get("read_at") is not None, read_at=d.get("read_at"),
            arrival=ArrivalOut(visitor_name=data["visitor_name"], host_name=data.get("host_name"),
                               gate_name=data.get("gate_name"), department_name=data.get("department_name"),
                               check_in_at=data["check_in_at"]),
            email_status=d["email"]["status"],
        )


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None = None
    unread_count: int


class MarkedAllRead(BaseModel):
    marked: int
    unread_count: int
