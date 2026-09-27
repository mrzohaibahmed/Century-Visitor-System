"""
Application settings, read from environment variables (prefix CG_) or api/.env.

Secrets (the MongoDB URI) exist only here, on the server. They are never sent
to the browser or to the Next.js frontend.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parents[2]

# The desktop application's database. The web application must never use it.
LEGACY_DATABASE_NAMES = frozenset({"century_gate_system"})

APP_VERSION = "0.1.0"


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
    # Private folder on the API server; never served directly, never inside web/.
    # Files have random names; the database holds only that name. Back this folder up
    # together with the database. Production must set it explicitly.
    photo_dir: Path = API_DIR.parent / ".dev" / "photos"
    photo_max_bytes: int = Field(default=2 * 1024 * 1024, ge=10_000, le=10 * 1024 * 1024)

    # --- Visitor passes / badges (Phase 4) ----------------------------------------
    # A pass (QR on the badge) stops working at check-out, when replaced, or after this long.
    pass_valid_hours: int = Field(default=24, ge=1, le=24 * 7)
    organization_name: str = Field(default="Century Gate", min_length=1, max_length=60)

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

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs if self.api_docs is not None else self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
