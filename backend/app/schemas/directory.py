"""Gates, departments and hosts."""
from pydantic import BaseModel, field_validator, model_validator

from app.core.identity import normalize_name, normalize_phone
from app.schemas.common import Email, IdStr, OptionalLongText, ShortText, StrictModel


def _at_least_one(model: BaseModel) -> BaseModel:
    if not any(v is not None for v in model.model_dump().values()):
        raise ValueError("Nothing to change.")
    return model


# ---------------------------------------------------------------- gates
class GateCreate(StrictModel):
    name: ShortText
    location: OptionalLongText | None = None


class GateUpdate(StrictModel):
    name: ShortText | None = None
    location: OptionalLongText | None = None
    is_active: bool | None = None

    _check = model_validator(mode="after")(_at_least_one)


class GateOut(BaseModel):
    id: str
    name: str
    location: str | None
    is_active: bool

    @classmethod
    def from_doc(cls, d: dict) -> "GateOut":
        return cls(id=str(d["_id"]), name=d["name"], location=d.get("location"), is_active=d["is_active"])


# ---------------------------------------------------------------- departments
class DepartmentCreate(StrictModel):
    name: ShortText
    notification_email: Email | None = None


class DepartmentUpdate(StrictModel):
    name: ShortText | None = None
    notification_email: Email | None = None
    is_active: bool | None = None

    _check = model_validator(mode="after")(_at_least_one)


class DepartmentOut(BaseModel):
    id: str
    name: str
    notification_email: str | None
    is_active: bool

    @classmethod
    def from_doc(cls, d: dict) -> "DepartmentOut":
        return cls(id=str(d["_id"]), name=d["name"], notification_email=d.get("notification_email"),
                   is_active=d["is_active"])


# ---------------------------------------------------------------- hosts
class _HostFields(StrictModel):
    @field_validator("name", check_fields=False)
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return normalize_name(v) if v is not None else v

    @field_validator("phone", check_fields=False)
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return normalize_phone(v) if v is not None else v


class HostCreate(_HostFields):
    name: str
    email: Email | None = None
    phone: str | None = None
    department_id: IdStr | None = None


class HostUpdate(_HostFields):
    name: str | None = None
    email: Email | None = None
    phone: str | None = None
    department_id: IdStr | None = None
    is_active: bool | None = None

    _check = model_validator(mode="after")(_at_least_one)


class HostOut(BaseModel):
    id: str
    name: str
    email: str | None
    phone: str | None
    department_id: str | None
    department_name: str | None = None
    is_active: bool

    @classmethod
    def from_doc(cls, d: dict, department_name: str | None = None) -> "HostOut":
        dep = d.get("department_id")
        return cls(id=str(d["_id"]), name=d["name"], email=d.get("email"), phone=d.get("phone"),
                   department_id=str(dep) if dep else None, department_name=department_name,
                   is_active=d["is_active"])
