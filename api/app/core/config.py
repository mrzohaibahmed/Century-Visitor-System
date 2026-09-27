"""
Application settings, read from environment variables (prefix CG_) or api/.env.

Secrets (the MongoDB URI) exist only here, on the server. They are never sent
to the browser or to the Next.js frontend.
"""
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, field_validator
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

    @property
    def docs_enabled(self) -> bool:
        return self.api_docs if self.api_docs is not None else self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
