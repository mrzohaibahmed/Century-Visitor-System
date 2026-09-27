"""
Health checks (public; used by the reverse proxy, monitoring and the UI status dot).

- /health/live  : the API process is up.
- /health/ready : the API can serve requests: database reachable, schema
                  migrated to the expected version, transactions available
                  (replica set), photo folder available. Answers 503
                  otherwise. Never reveals hosts, URIs, paths or error text.
"""
import asyncio
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel
from pymongo.errors import PyMongoError

from app.api.deps import get_database, get_settings, public
from app.core.config import APP_VERSION, Settings
from app.db.client import Database
from app.db.migrate import current_schema_version
from app.db.schema import SCHEMA_VERSION
from app.services.photos import photo_storage_available

log = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"], dependencies=[Depends(public)])

CheckState = Literal["ok", "unavailable", "missing", "outdated", "unknown"]
READY_TIMEOUT_SECONDS = 3


class LiveResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadyChecks(BaseModel):
    database: CheckState
    schema_version: CheckState
    transactions: CheckState
    photo_storage: CheckState


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: ReadyChecks


@router.get("/live", response_model=LiveResponse)
async def live() -> LiveResponse:
    return LiveResponse(status="ok", version=APP_VERSION)


@router.get("/ready", response_model=ReadyResponse, responses={503: {"model": ReadyResponse}})
async def ready(response: Response, database: Database = Depends(get_database),
                settings: Settings = Depends(get_settings)) -> ReadyResponse:
    checks = {"database": "unavailable", "schema_version": "unknown", "transactions": "unknown",
              "photo_storage": "ok" if photo_storage_available(settings) else "unavailable"}
    try:
        async with asyncio.timeout(READY_TIMEOUT_SECONDS):
            await database.db.command("ping")
            checks["database"] = "ok"
            version = await current_schema_version(database.db)
            checks["schema_version"] = ("ok" if version == SCHEMA_VERSION
                                        else "missing" if version is None else "outdated")
            hello = await database.db.command("hello")
            checks["transactions"] = "ok" if (hello.get("setName") or hello.get("msg") == "isdbgrid") else "unavailable"
    except (PyMongoError, TimeoutError) as e:
        log.warning("Readiness check failed (%s)", type(e).__name__)

    is_ready = all(state == "ok" for state in checks.values())
    response.status_code = 200 if is_ready else 503
    return ReadyResponse(status="ready" if is_ready else "not_ready", checks=ReadyChecks(**checks))
