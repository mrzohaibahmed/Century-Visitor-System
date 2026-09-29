"""E-mail (SMTP) settings for any provider. The SMTP password is accepted, never returned."""
import ipaddress
import re
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, SecretStr, StringConstraints, field_validator

from app.schemas.common import Email, StrictModel

Security = Literal["starttls", "ssl", "none"]          # the terms of CG_SMTP_SECURITY
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
_HOST_NAME = re.compile(rf"^{_LABEL}(?:\.{_LABEL})*$")


def _no_control(value: str | None, what: str) -> str | None:
    if value is not None and any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"The {what} must not contain control characters or line breaks.")
    return value


class EmailSettingsIn(StrictModel):
    """The whole setting. `password` omitted or null: keep the saved one. `username` empty: no login."""

    enabled: bool
    smtp_host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=253)]
    smtp_port: int = Field(ge=1, le=65535)
    security: Security
    username: Annotated[str, StringConstraints(strip_whitespace=True, max_length=254)] | None = None
    password: SecretStr | None = None
    from_email: Email
    from_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] | None = None
    reply_to: Email | None = None

    @field_validator("smtp_host")
    @classmethod
    def _host(cls, v: str) -> str:
        """A host name or an IP address (private addresses allowed: company mail servers). Nothing else:
        no scheme, port, path or user name."""
        try:
            ipaddress.ip_address(v)
            return v
        except ValueError:
            pass
        if not _HOST_NAME.match(v):
            raise ValueError("Enter a host name (e.g. smtp.example.com) or an IP address, without a port.")
        return v.lower()

    @field_validator("username", "from_name")
    @classmethod
    def _text(cls, v: str | None, info) -> str | None:
        return _no_control(v or None, info.field_name.replace("_", " "))

    @field_validator("password")
    @classmethod
    def _password(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None:
            return None
        text = v.get_secret_value()
        if not text or len(text) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in text):
            raise ValueError("The SMTP password must be 1–256 characters, without control characters.")
        return v


class EmailSettingsOut(BaseModel):
    """The saved settings, if any, and which settings are in use. Never the password: only its state."""

    source: Literal["database", "environment", "none"]
    environment_configured: bool                     # CG_SMTP_HOST set on the server (the fallback)
    saved: bool
    enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int | None = None
    security: Security | None = None
    username: str | None = None
    password_status: Literal["NOT_SET", "SAVED", "UNREADABLE"] = "NOT_SET"  # noqa: S105 - a status, not a password
    from_email: str | None = None
    from_name: str | None = None
    reply_to: str | None = None
    updated_at: datetime | None = None

    @classmethod
    def build(cls, doc: dict | None, source: str, environment_configured: bool, password_status: str
              ) -> "EmailSettingsOut":
        base = {"source": source, "environment_configured": environment_configured}
        if doc is None:
            return cls(**base, saved=False)
        return cls(**base, saved=True, enabled=doc["enabled"], smtp_host=doc["smtp_host"], smtp_port=doc["smtp_port"],
                   security=doc["security"], username=doc.get("username"), password_status=password_status,
                   from_email=doc["from_email"], from_name=doc.get("from_name"), reply_to=doc.get("reply_to"),
                   updated_at=doc.get("updated_at"))


class EmailTestIn(StrictModel):
    to: Email


class EmailTestOut(BaseModel):
    status: Literal["SENT", "FAILED"]
    code: str | None = None                  # e.g. EMAIL_AUTHENTICATION_FAILED
    message: str | None = None               # safe to show; never an SMTP reply or a credential
    source: Literal["database", "environment", "none"]
