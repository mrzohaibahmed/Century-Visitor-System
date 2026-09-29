"""Gate camera settings (administrators). The camera password is accepted, never returned."""
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, StringConstraints, field_validator

from app.schemas.common import StrictModel


class GateCameraIn(StrictModel):
    """The whole setting for one gate. `password` omitted or null: keep the saved one."""

    enabled: bool
    host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]
    protocol: Literal["http", "https"] = "https"
    port: int | None = Field(default=None, ge=1, le=65535)          # None: 443 (https) / 80 (http)
    channel: int = Field(default=101, ge=1, le=65535)
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    password: SecretStr | None = None
    timeout_seconds: float = Field(default=5, ge=1, le=30)

    @field_validator("password")
    @classmethod
    def _password(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None:
            return None
        text = v.get_secret_value()
        if not text.strip() or len(text) > 128 or any(ord(c) < 32 for c in text):
            raise ValueError("The camera password must be 1–128 characters, without control characters.")
        return v


class CameraLastTest(BaseModel):
    tested_at: datetime
    ok: bool
    code: str | None
    message: str | None
    model: str | None = None
    firmware: str | None = None
    device_name: str | None = None


class GateCameraOut(BaseModel):
    """One gate and its camera. Never the password: only whether one is saved and usable."""

    gate_id: str
    gate_name: str
    gate_active: bool
    configured: bool
    enabled: bool = False
    host: str | None = None
    protocol: Literal["http", "https"] | None = None
    port: int | None = None
    channel: int | None = None
    username: str | None = None
    password_status: Literal["NOT_SET", "SAVED", "UNREADABLE"] = "NOT_SET"  # noqa: S105 - a status, not a password
    timeout_seconds: float | None = None
    updated_at: datetime | None = None
    last_test: CameraLastTest | None = None

    @classmethod
    def build(cls, gate: dict, doc: dict | None, password_status: str) -> "GateCameraOut":
        base = {"gate_id": str(gate["_id"]), "gate_name": gate["name"], "gate_active": gate["is_active"]}
        if doc is None:
            return cls(**base, configured=False)
        last = doc.get("last_test")
        return cls(**base, configured=True, enabled=doc["enabled"], host=doc["host"], protocol=doc["protocol"],
                   port=doc.get("port"), channel=doc["channel"], username=doc["username"],
                   password_status=password_status, timeout_seconds=doc["timeout_seconds"],
                   updated_at=doc.get("updated_at"),
                   last_test=CameraLastTest(tested_at=last["at"], **{k: v for k, v in last.items() if k != "at"})
                   if last else None)


class CameraTestOut(BaseModel):
    status: Literal["CONNECTED", "FAILED"]
    tested_at: datetime
    code: str | None = None                  # e.g. CAMERA_AUTHENTICATION_FAILED
    message: str | None = None               # safe to show; never contains camera replies or credentials
    model: str | None = None
    firmware: str | None = None
    device_name: str | None = None
