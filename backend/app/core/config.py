"""
Application settings, read from environment variables (prefix CG_) or backend/.env.

Secrets (the MongoDB URI) exist only here, on the server. They are never sent
to the browser or to the Next.js frontend.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pymongo.errors import ConfigurationError, InvalidURI
from pymongo.uri_parser import parse_uri

API_DIR = Path(__file__).resolve().parents[2]

# The desktop application's database. The web application must never use it.
LEGACY_DATABASE_NAMES = frozenset({"century_gate_system"})

APP_VERSION = "0.1.0"

# Connection options that switch off certificate or host-name checks: refused in production.
_INSECURE_TLS_OPTIONS = ("tlsInsecure", "tlsAllowInvalidCertificates", "tlsAllowInvalidHostnames")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CG_",
        env_file=API_DIR / ".env",          # absolute: does not depend on the working directory
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"

    mongo_uri: SecretStr = SecretStr("mongodb://127.0.0.1:27018/?replicaSet=cgvms-dev")
    mongo_db: str = "century_gate_vms"
    mongo_timeout_ms: int = Field(default=5000, ge=100, le=60_000)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Organisation time zone: "today" on the dashboard and in reports is computed in it.
    timezone: str = "Asia/Karachi"

    # Interactive API docs (/api/docs). Default: on in development only.
    api_docs: bool | None = None

    # --- Sessions -------------------------------------------------------------
    # Idle timeout: a gate PC left alone is logged out. Absolute limit: one shift.
    session_idle_minutes: int = Field(default=15, ge=1, le=24 * 60)
    session_max_hours: int = Field(default=12, ge=1, le=72)
    # Secure cookies (HTTPS only; browsers also accept them on http://localhost).
    # Only set to false for a plain-HTTP test network; never in production.
    cookie_secure: bool = True

    # --- Login protection -------------------------------------------------------
    login_max_failures: int = Field(default=5, ge=1, le=50)         # per account, then locked
    login_lockout_minutes: int = Field(default=15, ge=1, le=24 * 60)
    login_ip_limit: int = Field(default=30, ge=1, le=10_000)         # attempts per client IP per window
    login_ip_window_minutes: int = Field(default=15, ge=1, le=24 * 60)

    # Proxies whose X-Forwarded-For header is trusted to name the real client IP
    # (the reverse proxy in production; Next.js on this machine in development).
    trusted_proxies: list[str] = ["127.0.0.1", "::1"]

    # --- Visitor photos (Phase 4) -------------------------------------------------
    # Private folder on the API server; never served directly, never inside frontend/.
    # Files have random names; the database holds only that name. Back this folder up
    # together with the database. Production must set it explicitly.
    photo_dir: Path = API_DIR.parent / ".dev" / "photos"
    photo_max_bytes: int = Field(default=2 * 1024 * 1024, ge=10_000, le=10 * 1024 * 1024)

    # --- Visitor passes / badges (Phase 4) ----------------------------------------
    # A pass (QR on the badge) stops working at check-out, when replaced, or after this long.
    pass_valid_hours: int = Field(default=24, ge=1, le=24 * 7)
    organization_name: str = Field(default="Century Gate", min_length=1, max_length=60)

    # --- E-mail to hosts (Phase 6A) ---------------------------------------------------
    # Leave CG_SMTP_HOST empty to switch e-mail off (in-app notifications still work).
    # The password lives only here (server environment), never in the database or logs.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"     # none: internal relay only
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None                                        # e.g. "Century Gate VMS <vms@example.com>"
    smtp_timeout_seconds: int = Field(default=20, ge=1, le=120)
    # The background sender inside the API process (tests switch it off and drive it directly).
    email_worker: bool = True

    @field_validator("mongo_db")
    @classmethod
    def _not_the_legacy_database(cls, value: str) -> str:
        if value.strip().lower() in LEGACY_DATABASE_NAMES:
            raise ValueError(
                f"'{value}' is the legacy desktop database. The web application must use its own database.")
        if not value or any(ch in value for ch in '/\\. "$'):
            raise ValueError("Invalid MongoDB database name.")
        return value

    @field_validator("timezone")
    @classmethod
    def _valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f"Unknown time zone '{value}'.") from e
        return value

    @field_validator("cookie_secure")
    @classmethod
    def _secure_cookies_in_production(cls, value: bool, info) -> bool:
        if not value and info.data.get("environment") == "production":
            raise ValueError("cookie_secure must be true in production.")
        return value

    @model_validator(mode="after")
    def _explicit_photo_dir_in_production(self):
        if self.environment == "production" and "photo_dir" not in self.model_fields_set:
            raise ValueError("CG_PHOTO_DIR must be set in production (a private folder that is backed up).")
        return self

    @model_validator(mode="after")
    def _secure_database_connection_in_production(self):
        """Production refuses a database connection without a login, without TLS, or with
        certificate checks switched off (the messages never contain the URI or password)."""
        if self.environment != "production":
            return self
        try:
            # validate=False: option values stay text and the CA file is not opened here
            # (a missing file is reported when connecting).
            parsed = parse_uri(self.mongo_uri.get_secret_value(), validate=False)
        except (InvalidURI, ConfigurationError, ValueError):
            raise ValueError("CG_MONGO_URI is not a valid MongoDB connection string.") from None
        options = parsed["options"]

        def enabled(name: str) -> bool:
            return str(options.get(name, "")).strip().lower() == "true"

        if not parsed.get("username") or not parsed.get("password"):
            raise ValueError("CG_MONGO_URI must include the application's database user and password in production.")
        if not (enabled("tls") or enabled("ssl")):
            raise ValueError("CG_MONGO_URI must use TLS in production (tls=true with tlsCAFile).")
        for insecure in _INSECURE_TLS_OPTIONS:
            if enabled(insecure):
                raise ValueError(f"CG_MONGO_URI must not use {insecure} in production: "
                                 "the database certificate has to be validated.")
        return self

    @model_validator(mode="after")
    def _smtp_settings(self):
        if not self.smtp_host:
            return self
        if not self.smtp_from:
            raise ValueError("CG_SMTP_FROM (the sender address) is required when CG_SMTP_HOST is set.")
        if bool(self.smtp_username) != bool(self.smtp_password and self.smtp_password.get_secret_value()):
            raise ValueError("Set both CG_SMTP_USERNAME and CG_SMTP_PASSWORD, or neither.")
        if self.environment == "production" and self.smtp_username and self.smtp_security == "none":
            raise ValueError("CG_SMTP_SECURITY=none would send the SMTP password unencrypted; use starttls or ssl.")
        return self

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs if self.api_docs is not None else self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configuration_problems(error: ValidationError) -> str:
    """The reasons settings were refused, WITHOUT the submitted values (they may hold the database password)."""
    return "; ".join(str(e.get("msg", "invalid")).removeprefix("Value error, ") for e in error.errors())
