from fastapi import APIRouter

from app.api.v1 import (
    auth,
    directory,
    email_settings,
    gate_cameras,
    health,
    notifications,
    passes,
    photos,
    reports,
    users,
    visitors,
    visits,
    watchlist,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(directory.gates)
api_router.include_router(directory.departments)
api_router.include_router(directory.hosts)
api_router.include_router(visitors.router)
api_router.include_router(visits.router)
api_router.include_router(watchlist.router)
api_router.include_router(photos.router)
api_router.include_router(passes.visit_passes)
api_router.include_router(passes.scans)
api_router.include_router(notifications.router)
api_router.include_router(gate_cameras.router)
api_router.include_router(gate_cameras.session_router)
api_router.include_router(email_settings.router)
api_router.include_router(reports.router)
