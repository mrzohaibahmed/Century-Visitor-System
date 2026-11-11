"""
Which database this process uses: CG_DB_BACKEND = "mongo" (default, the current system) or "mssql"
(SQL Server, being built area by area). Chosen ONCE per process, before the repositories load.

Only this one setting is read here (environment, else backend/.env). The full Settings are not loaded
at import time: a configuration error must reach serve.py's clear message, never an import traceback.
"""
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import API_DIR

Backend = Literal["mongo", "mssql"]


class _BackendSetting(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CG_", env_file=API_DIR / ".env", env_file_encoding="utf-8",
                                      extra="ignore")
    db_backend: Backend = "mongo"


BACKEND: Backend = _BackendSetting().db_backend
