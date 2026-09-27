"""Visitors (the person) and watchlist screening results."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints, field_validator, model_validator

from app.core.identity import IdentityType, normalize_identity, normalize_name, normalize_phone
from app.schemas.common import StrictModel


class IdentityIn(StrictModel):
    type: IdentityType
    number: Annotated[str, StringConstraints(min_length=1, max_length=60)]

    @model_validator(mode="after")
    def _normalise(self):
        self.number = normalize_identity(self.type, self.number)
        return self


class _VisitorFields(StrictModel):
    @field_validator("full_name", check_fields=False)
    @classmethod
    def _name(cls, v):
        return normalize_name(v) if v is not None else v

    @field_validator("phone", check_fields=False)
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if v is not None else v


class VisitorCreate(_VisitorFields):
    full_name: str
    identity: IdentityIn
    phone: str | None = None


class VisitorUpdate(_VisitorFields):
    full_name: str | None = None
    identity: IdentityIn | None = None
    phone: str | None = None

    @model_validator(mode="after")
    def _something(self):
        if self.full_name is None and self.identity is None and self.phone is None:
            raise ValueError("Nothing to change.")
        return self


class IdentityOut(BaseModel):
    type: IdentityType
    number: str


class ActiveVisitRef(BaseModel):
    id: str
    visit_number: str
    check_in_at: datetime
    gate_name: str | None


class VisitorOut(BaseModel):
    id: str
    full_name: str
    identity: IdentityOut | None
    phone: str | None
    created_at: datetime
    updated_at: datetime
    active_visit: ActiveVisitRef | None = None
    photo_id: str | None = None           # the current photo (GET /photos/{id}); never the image itself

    @classmethod
    def from_doc(cls, d: dict, active: dict | None = None) -> "VisitorOut":
        ident = d.get("identity")
        return cls(
            id=str(d["_id"]), full_name=d["full_name"],
            identity=IdentityOut(type=ident["type"], number=ident["number"]) if ident else None,
            phone=d.get("phone"), created_at=d["created_at"], updated_at=d["updated_at"],
            active_visit=ActiveVisitRef(id=str(active["_id"]), visit_number=active["visit_number"],
                                        check_in_at=active["check_in_at"],
                                        gate_name=active.get("snapshot", {}).get("gate_name")) if active else None,
            photo_id=str(d["current_photo_id"]) if d.get("current_photo_id") else None,
        )


class ScreeningOut(BaseModel):
    status: Literal["CLEAR", "BLOCKED"]
    reason: str | None = None


class VisitorLookupOut(BaseModel):
    visitor: VisitorOut
    screening: ScreeningOut
