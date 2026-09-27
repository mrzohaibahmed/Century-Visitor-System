"""Visitor photos: upload at check-in, and the authorised way to see one."""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.errors import AppError
from app.core.images import ACCEPTED_CONTENT_TYPES
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.photos import PhotoOut
from app.services import photos as svc
from app.services.auth import AuthContext

router = APIRouter(tags=["photos"])


async def _read_limited(request: Request, limit: int) -> bytes:
    too_large = AppError(413, "photo_too_large", f"The photo is too large (at most {limit // 1024} KB).")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_large
    chunks, size = [], 0
    async for chunk in request.stream():           # stop reading as soon as the limit is passed
        size += len(chunk)
        if size > limit:
            raise too_large
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/visitors/{visitor_id}/photo", response_model=PhotoOut, status_code=201)
async def upload_photo(visitor_id: str, request: Request,
                       ctx: AuthContext = Depends(require(Permission.PHOTO_CAPTURE)),
                       database: Database = Depends(get_database),
                       settings: Settings = Depends(get_settings)) -> PhotoOut:
    """The request body is the image itself (Content-Type image/jpeg, image/png or image/webp)."""
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in ACCEPTED_CONTENT_TYPES:
        raise AppError(415, "unsupported_media_type", "The photo must be a JPEG, PNG or WebP image.")
    data = await _read_limited(request, settings.photo_max_bytes)
    doc = await svc.capture(database.db, settings, ctx, request_meta(request), visitor_id, data)
    return PhotoOut.from_doc(doc)


@router.get("/photos/{photo_id}", response_class=Response,
            responses={200: {"content": {"image/jpeg": {}}, "description": "The photo"}})
async def get_photo(photo_id: str, request: Request, ctx: AuthContext = Depends(require(Permission.PHOTO_VIEW)),
                    database: Database = Depends(get_database), settings: Settings = Depends(get_settings)) -> Response:
    data, content_type = await svc.read(database.db, settings, ctx, request_meta(request), photo_id)
    # Personal data: never cached (the middleware also sets no-store), shown inline only.
    return Response(content=data, media_type=content_type,
                    headers={"Cache-Control": "no-store, private", "Content-Disposition": "inline"})
