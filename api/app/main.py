"""
FastAPI application factory.

Run (development):  uvicorn app.main:create_app --factory --reload --port 8000
All endpoints live under /api/v1; the reverse proxy (production) or the Next.js
dev rewrite forwards the browser's same-origin /api/* requests here.
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import APP_VERSION, Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.security import burn_verify_time
from app.db.client import Database
from app.services.photos import check_photo_dir

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Fails the start-up (the service stops with this message in its log) rather than running without photos.
        check_photo_dir(settings, create=settings.environment != "production")
        app.state.database = Database(settings)
        log.info("API starting (version %s, environment %s, database %s)",
                 APP_VERSION, settings.environment, settings.mongo_db)
        # Prepare the timing-equaliser hash now, so the first unknown-user login is not slower.
        warm_up = asyncio.create_task(asyncio.to_thread(burn_verify_time, "warm-up"))
        try:
            yield
        finally:
            warm_up.cancel()
            await app.state.database.close()
            log.info("API stopped")

    docs = settings.docs_enabled
    app = FastAPI(
        title="Century Gate VMS API",
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    app.state.settings = settings
    install_error_handlers(app)
    # Added last = runs first: the request ID exists before anything else happens.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(api_router, prefix="/api/v1")
    return app
