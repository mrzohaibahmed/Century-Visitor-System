"""
Request/response models for users and authentication.

Requests forbid unknown fields (no mass assignment: a client cannot slip in
`role`, `is_active` or `password_hash`). Responses never contain password
hashes, session tokens or CSRF tokens.
"""
from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.core.permissions import ROLE_PERMISSIONS, Role

Username = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
Password = Annotated[str, StringConstraints(min_length=1, max_length=256)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- requests
class LoginRequest(StrictModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    password: Password


class ChangePasswordRequest(StrictModel):
    current_password: Password
    new_password: Password


class UserCreateRequest(StrictModel):
    username: Username
    display_name: DisplayName
    role: Role
    password: Password = Field(description="Temporary password; the user must change it at first login.")


class UserUpdateRequest(StrictModel):
    display_name: DisplayName | None = None
    role: Role | None = None
    is_active: bool | None = None
    confirm_password: Password | None = Field(
        default=None, description="The acting admin's own password; required to change role or active state.")

    @model_validator(mode="after")
    def _something_to_change(self):
        if self.display_name is None and self.role is None and self.is_active is None:
            raise ValueError("Nothing to change.")
        return self


class PasswordResetRequest(StrictModel):
    new_password: Password
    confirm_password: Password | None = Field(default=None, description="The acting admin's own password.")


# ---------------------------------------------------------------- responses
class UserOut(BaseModel):
    id: str
    username: str
    display_name: str | None
    role: Role
    is_active: bool
    must_change_password: bool
    locked: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_doc(cls, doc: dict) -> "UserOut":
        locked_until = doc.get("locked_until")
        return cls(
            id=str(doc["_id"]), username=doc["username"], display_name=doc.get("display_name"),
            role=Role(doc["role"]), is_active=doc.get("is_active", False),
            must_change_password=doc.get("must_change_password", False),
            locked=bool(locked_until and locked_until > datetime.now(UTC)),
            last_login_at=doc.get("last_login_at"), created_at=doc["created_at"], updated_at=doc["updated_at"],
        )


class SessionInfo(BaseModel):
    expires_at: datetime
    idle_timeout_minutes: int


class MeResponse(BaseModel):
    user: UserOut
    permissions: list[str]
    session: SessionInfo

    @classmethod
    def build(cls, user: dict, session: dict, idle_minutes: int) -> "MeResponse":
        role = Role(user["role"])
        return cls(user=UserOut.from_doc(user), permissions=sorted(str(p) for p in ROLE_PERMISSIONS[role]),
                   session=SessionInfo(expires_at=session["expires_at"], idle_timeout_minutes=idle_minutes))


class UserListResponse(BaseModel):
    items: list[UserOut]
