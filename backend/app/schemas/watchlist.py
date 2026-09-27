"""Watchlist management (administrators)."""
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, StringConstraints, field_validator, model_validator

from app.core.identity import normalize_name
from app.schemas.common import StrictModel
from app.schemas.visitors import IdentityIn, IdentityOut
from app.schemas.visits import PersonRef

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=200)]


class WatchlistStatus(StrEnum):
    ACTIVE = "ACTIVE"          # blocks entry
    EXPIRED = "EXPIRED"        # its end date has passed; no longer blocks
    DISABLED = "DISABLED"      # lifted by an administrator; no longer blocks


def _future(value: datetime | None) -> datetime | None:
    if value is not None and value <= datetime.now(UTC):
        raise ValueError("The end date must be in the future.")
    return value


class _NameField(StrictModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _name(cls, v):
        return normalize_name(v) if v else None


class WatchlistCreate(_NameField):
    identity: IdentityIn                   # normalised on the server (IdentityIn)
    name: str | None = None                # optional; taken from the visitor record if registered
    reason: Reason
    expires_at: AwareDatetime | None = None

    _check_expiry = field_validator("expires_at")(_future)


class WatchlistUpdate(_NameField):
    """The ID number cannot be changed: disable the entry and add a correct one (keeps the history honest)."""
    name: str | None = None
    reason: Reason | None = None
    expires_at: AwareDatetime | None = None
    clear_expiry: bool = False             # true: the entry no longer has an end date

    _check_expiry = field_validator("expires_at")(_future)

    @model_validator(mode="after")
    def _rules(self):
        if self.clear_expiry and self.expires_at is not None:
            raise ValueError("Either set an end date or remove it, not both.")
        if self.name is None and self.reason is None and self.expires_at is None and not self.clear_expiry:
            raise ValueError("Nothing to change.")
        return self


class WatchlistDisable(StrictModel):
    note: Note                             # why the ban is lifted (kept on the entry and in the audit trail)


def status_of(d: dict, now: datetime | None = None) -> WatchlistStatus:
    if not d.get("is_active"):
        return WatchlistStatus.DISABLED
    expires = d.get("expires_at")
    if expires is not None and expires <= (now or datetime.now(UTC)):
        return WatchlistStatus.EXPIRED
    return WatchlistStatus.ACTIVE


class WatchlistOut(BaseModel):
    id: str
    identity: IdentityOut
    name: str | None
    reason: str
    status: WatchlistStatus
    expires_at: datetime | None
    created_at: datetime
    created_by: PersonRef
    updated_at: datetime | None
    disabled_at: datetime | None
    disabled_by: PersonRef | None
    disabled_reason: str | None

    @classmethod
    def from_doc(cls, d: dict) -> "WatchlistOut":
        disabled_by = d.get("disabled_by")
        return cls(
            id=str(d["_id"]), identity=IdentityOut(**d["identity"]), name=d.get("name"), reason=d["reason"],
            status=status_of(d), expires_at=d.get("expires_at"), created_at=d["created_at"],
            created_by=PersonRef(id=str(d["created_by"]), name=d.get("created_by_name")),
            updated_at=d.get("updated_at"), disabled_at=d.get("disabled_at"),
            disabled_by=PersonRef(id=str(disabled_by), name=d.get("disabled_by_name")) if disabled_by else None,
            disabled_reason=d.get("disabled_reason"),
        )


class WatchlistCreated(WatchlistOut):
    # Set when the person is inside right now: security should be told at once.
    inside_visit_number: str | None = None
