"""Gate cameras (administrators only): settings per gate, connection test and test photo.

The camera password can be set here but is never returned. Tests use the saved settings and never
store a picture. Guards do not use these routes (check-in capture comes in a later step).
"""
from fastapi import APIRouter, Depends, Request, Response

from app.api.deps import get_database, get_settings, request_meta, require
from app.core.config import Settings
from app.core.errors import AppError
from app.core.permissions import Permission
from app.db.client import Database
from app.schemas.gate_cameras import CameraTestOut, GateCameraIn, GateCameraOut
from app.services import camera_settings as svc
from app.services.auth import AuthContext

router = APIRouter(prefix="/gate-cameras", tags=["gate cameras"])
manage = require(Permission.SETTINGS_MANAGE)


@router.get("", response_model=list[GateCameraOut])
async def list_gate_cameras(ctx: AuthContext = Depends(manage), database: Database = Depends(get_database),
                            settings: Settings = Depends(get_settings)) -> list[GateCameraOut]:
    return [GateCameraOut.build(gate, doc, svc.password_status(doc, settings) if doc else "NOT_SET")
            for gate, doc in await svc.list_for_admin(database.db)]


@router.put("/{gate_id}", response_model=GateCameraOut)
async def save_gate_camera(gate_id: str, body: GateCameraIn, request: Request, ctx: AuthContext = Depends(manage),
                           database: Database = Depends(get_database),
                           settings: Settings = Depends(get_settings)) -> GateCameraOut:
    gate, doc = await svc.save(database.db, settings, ctx, request_meta(request), gate_id,
                               body.model_dump(exclude={"password"}), body.password)
    return GateCameraOut.build(gate, doc, svc.password_status(doc, settings))


@router.delete("/{gate_id}", status_code=204)
async def remove_gate_camera(gate_id: str, request: Request, ctx: AuthContext = Depends(manage),
                             database: Database = Depends(get_database)) -> Response:
    await svc.remove(database.db, ctx, request_meta(request), gate_id)
    return Response(status_code=204)


@router.post("/{gate_id}/test", response_model=CameraTestOut)
async def test_gate_camera(gate_id: str, request: Request, ctx: AuthContext = Depends(manage),
                           database: Database = Depends(get_database),
                           settings: Settings = Depends(get_settings)) -> CameraTestOut:
    """Reachable, login accepted, and what the camera says it is. A failed test is a result, not an error."""
    r = await svc.test_connection(database.db, settings, ctx, request_meta(request), gate_id)
    device = r.device
    return CameraTestOut(status="CONNECTED" if r.ok else "FAILED", tested_at=r.tested_at, code=r.code,
                         message=r.message, model=device.model if device else None,
                         firmware=device.firmware if device else None,
                         device_name=device.device_name if device else None)


@router.post("/{gate_id}/test-photo", response_class=Response,
             responses={200: {"content": {"image/jpeg": {}}, "description": "The test picture, as the VMS keeps it"}})
async def test_gate_camera_photo(gate_id: str, request: Request, ctx: AuthContext = Depends(manage),
                                 database: Database = Depends(get_database),
                                 settings: Settings = Depends(get_settings)) -> Response:
    """One snapshot, validated and scaled exactly like a visitor photo, returned and not stored."""
    r = await svc.test_photo(database.db, settings, ctx, request_meta(request), gate_id)
    if not r.ok:
        status = 422 if r.code == "CAMERA_IMAGE_UNUSABLE" else 502
        raise AppError(status, r.code.lower(), r.message)
    headers = {"Cache-Control": "no-store, private", "Content-Disposition": "inline",
               "X-Camera-Width": str(r.camera_size[0]), "X-Camera-Height": str(r.camera_size[1]),
               "X-Photo-Width": str(r.photo.width), "X-Photo-Height": str(r.photo.height)}
    return Response(content=r.photo.data, media_type=r.photo.content_type, headers=headers)
