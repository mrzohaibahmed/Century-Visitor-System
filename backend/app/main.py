"""
FastAPI application factory.

Run (development):  uvicorn app.main:create_app --factory --reload --port 8000
All endpoints live under /api/v1; the reverse proxy (production) or the Next.js
dev rewrite forwards the browser's same-origin /api/* requests here.
"""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import APP_VERSION, Settings, get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, SecurityHeadersMiddleware
from app.core.security import burn_verify_time
from app.db.client import open_database
from app.db.sql.cleanup import CleanupWorker
from app.services.notifications import EmailWorker, OverstayWorker
from app.services.photos import check_photo_dir

log = logging.getLogger(__name__)

SHUTDOWN_GRACE_SECONDS = 10          # how long background workers get to finish their current pass


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Fails the start-up (the service stops with this message in its log) rather than running without photos.
        check_photo_dir(settings, create=settings.environment != "production")
        app.state.database = open_database(settings)
        log.info("API starting (version %s, environment %s, database %s)",
                 APP_VERSION, settings.environment, app.state.database.name)
        if not settings.secure_cookies and settings.environment == "production":
            log.warning("Deployment mode http-lan: plain HTTP on a trusted LAN, cookies without Secure; "
                        "traffic between browsers and this server is not encrypted.")
        # Prepare the timing-equaliser hash now, so the first unknown-user login is not slower.
        warm_up = asyncio.create_task(asyncio.to_thread(burn_verify_time, "warm-up"))
        # Host e-mails (Phase 6A): sent in the background, never during a request. Always running, so
        # SMTP settings saved later by an administrator work without a restart; with e-mail off it
        # finds nothing to send.
        app.state.email_worker = None
        workers: list = []
        if settings.email_worker:
            app.state.email_worker = EmailWorker(app.state.database.db, settings)
            workers.append(app.state.email_worker)
            # Overstay e-mails reuse the same SMTP queue; wake the sender when new rows are queued.
            workers.append(OverstayWorker(app.state.database.db, settings, on_queued=app.state.email_worker.wake))
        # SQL Server has no TTL indexes: expired sessions and rate-limit windows are deleted here.
        workers.append(CleanupWorker(app.state.database.db))
        background = [asyncio.create_task(worker.run()) for worker in workers]
        try:
            yield
        finally:
            warm_up.cancel()
            # Stop the workers between passes, not by cancelling them mid-query: with SQL Server a driver
            # call runs in a thread that a cancellation does not stop, and closing its connection under it
            # crashes the process. Cancel only what has not stopped by itself after a few seconds.
            for worker in workers:
                worker.stop()
            if background:
                _, still_running = await asyncio.wait(background, timeout=SHUTDOWN_GRACE_SECONDS)
                for task in still_running:
                    task.cancel()
                for task in still_running:
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
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
