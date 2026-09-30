"""
Gate camera settings (administrators): one Hikvision camera per gate, and its connection tests.

Stored in the `settings` collection, one document per gate: _id "gate_camera:<gate id>". The gate
itself is not changed. The camera password is encrypted (core/secrets.py, AES-256-GCM, key in
CG_SECRETS_KEY) with the document id as associated data; it is never returned, logged or audited.
The API only says whether a password is saved.

Changing where the password goes (address, connection, port or user name) requires entering the
password again: otherwise an administrator's session could send the saved password's Digest answer
to another machine.

Tests use the saved settings (the password is never sent back to the browser to test with). They
never store a photo: the test picture is only checked with the same validation as visitor photos
(core/images.normalize_photo) and returned. One request per camera at a time (tests and check-in
captures share the lock): repeated failed logins lock Hikvision accounts.

Check-in capture (guards): the camera is the one of the SESSION's gate (services/auth.session_gate),
never one named by the browser. The picture is returned as a preview only; the guard's "Use this
photo" uploads it through the normal visitor photo endpoint (services/photos.capture), which stays
the only way a visitor photo is stored.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from bson import ObjectId
from pydantic import SecretStr
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core import secrets
from app.core.config import Settings
from app.core.errors import AppError
from app.core.images import InvalidImageError, NormalizedPhoto, normalize_photo
from app.db.transactions import run_in_transaction
from app.services import audit
from app.services import directory as directory_svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta, session_gate
from app.services.gate_camera import CameraConfig, CameraError, DeviceInfo, GateCameraClient, Snapshot

log = logging.getLogger(__name__)

# Fields that decide where the saved password is sent: changing one needs the password again.
DESTINATION_FIELDS = ("host", "protocol", "port", "username")
SETTINGS_FIELDS = ("enabled", "host", "protocol", "port", "channel", "username", "timeout_seconds")

NOT_CONFIGURED = AppError(404, "camera_not_configured", "No camera is set up for this gate.")
KEY_MISSING = AppError(503, "secrets_key_missing",
                       "Camera passwords cannot be used: the server has no CG_SECRETS_KEY. Ask the administrator.")
BUSY = AppError(409, "camera_test_running", "A test of this camera is already running. Wait for it to finish.")

_testing: dict[ObjectId, asyncio.Lock] = {}


def doc_id(gate_id: ObjectId) -> str:
    return f"gate_camera:{gate_id}"


def password_status(doc: dict, settings: Settings) -> str:
    """NOT_SET, SAVED, or UNREADABLE (encrypted with another key, or no key on the server now)."""
    sealed = doc.get("password")
    if not sealed:
        return "NOT_SET"
    key = settings.secrets_key_bytes
    return "SAVED" if key and sealed.get("kid") == secrets.key_id(key) else "UNREADABLE"


async def list_for_admin(db: AsyncDatabase) -> list[tuple[dict, dict | None]]:
    """Every gate (active first, by name) with its camera settings document, if any."""
    gates = await db.gates.find({}).sort([("is_active", -1), ("name", 1)]).to_list(length=directory_svc.MAX_LIST)
    docs = await db.settings.find({"_id": {"$in": [doc_id(g["_id"]) for g in gates]}}).to_list(length=len(gates))
    by_id = {d["_id"]: d for d in docs}
    return [(g, by_id.get(doc_id(g["_id"]))) for g in gates]


def _config(values: dict, password: str) -> CameraConfig:
    """The camera configuration; its checks (host, port, channel, ...) are the single source of truth."""
    try:
        return CameraConfig(host=values["host"], protocol=values["protocol"], port=values.get("port"),
                            channel=values["channel"], username=values["username"], password=SecretStr(password),
                            timeout=values["timeout_seconds"])
    except ValueError as e:
        raise AppError(422, "invalid_camera_settings", str(e)) from None


async def save(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta, gate_id: str,
               data: dict, password: SecretStr | None) -> tuple[dict, dict]:
    """Creates or replaces a gate's camera settings. `password` None keeps the saved one."""
    gate = await directory_svc.get(db, directory_svc.GATE, gate_id)
    _id = doc_id(gate["_id"])
    current = await db.settings.find_one({"_id": _id})
    values = {k: data[k] for k in SETTINGS_FIELDS}
    new_password = password.get_secret_value() if password is not None else None

    if new_password is None:
        if current is None or not current.get("password"):
            raise AppError(422, "camera_password_required", "Enter the camera password.")
        moved = [k for k in DESTINATION_FIELDS if values.get(k) != current.get(k)]
        if moved:
            raise AppError(422, "camera_password_required",
                           "Enter the camera password again when changing the address, connection, port or user name.")
    _config(values, new_password or "unchanged")         # validate everything before anything is written

    key = settings.secrets_key_bytes
    fields = dict(values)
    if new_password is not None:
        if key is None:
            raise KEY_MISSING
        fields["password"] = secrets.encrypt(key, new_password, _id)
    changed = {k for k in values if current is None or current.get(k) != values[k]}
    if current is not None and not changed and new_password is None:
        return gate, current                             # nothing to save
    now = datetime.now(UTC)
    unset = {}
    if current is not None and (changed & {*DESTINATION_FIELDS, "channel"} or new_password is not None):
        unset["last_test"] = ""                          # an earlier test result no longer applies

    async def work(s: AsyncClientSession):
        update = {"$set": {**fields, "type": "gate_camera", "gate_id": gate["_id"], "updated_at": now,
                           "updated_by": ctx.user["_id"]},
                  "$setOnInsert": {"created_at": now}}
        if unset:
            update["$unset"] = unset
        await db.settings.update_one({"_id": _id}, update, upsert=True, session=s)
        diff = {k: {"from": current.get(k) if current else None, "to": values[k]} for k in sorted(changed)}
        if new_password is not None:
            diff["password"] = "changed"  # noqa: S105 - the fact only, never the value
        await audit.record(db, AuditAction.GATE_CAMERA_UPDATED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="gates", resource_id=gate["_id"], changes=diff or None, session=s)

    await run_in_transaction(db, work)
    return gate, await db.settings.find_one({"_id": _id})


async def remove(db: AsyncDatabase, ctx: AuthContext, meta: RequestMeta, gate_id: str) -> None:
    """Deletes a gate's camera settings, password included."""
    gate = await directory_svc.get(db, directory_svc.GATE, gate_id)

    async def work(s: AsyncClientSession):
        result = await db.settings.delete_one({"_id": doc_id(gate["_id"])}, session=s)
        if result.deleted_count == 0:
            raise NOT_CONFIGURED
        await audit.record(db, AuditAction.GATE_CAMERA_REMOVED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="gates", resource_id=gate["_id"], session=s)

    await run_in_transaction(db, work)


async def client_for(db: AsyncDatabase, settings: Settings, gate_id: ObjectId) -> GateCameraClient:
    """A client with the saved settings and the decrypted password (kept only in memory)."""
    doc = await db.settings.find_one({"_id": doc_id(gate_id)})
    if doc is None:
        raise NOT_CONFIGURED
    key = settings.secrets_key_bytes
    if key is None:
        raise KEY_MISSING
    try:
        password = secrets.decrypt(key, doc.get("password"), doc["_id"])
    except secrets.SecretUnreadable:
        raise AppError(409, "camera_password_unreadable",
                       "The saved camera password cannot be read (the server key has changed). "
                       "Enter the camera password again.") from None
    return GateCameraClient(_config(doc, password))


@dataclass(frozen=True)
class CameraTestResult:
    ok: bool
    tested_at: datetime
    code: str | None = None               # CameraErrorCode value, or CAMERA_IMAGE_UNUSABLE
    message: str | None = None
    device: DeviceInfo | None = None
    photo: NormalizedPhoto | None = None  # test picture as the VMS would keep it (never stored)
    camera_size: tuple[int, int] | None = None


# ---------------------------------------------------------------- check-in capture (guards)
UNAVAILABLE_AT_GATE = AppError(404, "gate_camera_unavailable",
                               "This gate has no camera to use. Use the webcam, or continue without a photo.")
UNUSABLE_AT_GATE = AppError(409, "gate_camera_unavailable",
                            "The gate camera cannot be used right now. Use the webcam and tell the administrator.")
CAMERA_BUSY = AppError(409, "gate_camera_busy", "The gate camera is busy. Try again in a moment.")


async def session_camera(db: AsyncDatabase, settings: Settings, ctx: AuthContext) -> tuple[dict, dict] | None:
    """(gate, camera settings) for the session's gate when its camera is switched on and has a usable
    password; else None. Never contacts the camera."""
    gate, _ = await session_gate(db, ctx.session)
    if gate is None:
        return None
    doc = await db.settings.find_one({"_id": doc_id(gate["_id"])})
    if doc is None or not doc.get("enabled") or password_status(doc, settings) != "SAVED":
        return None
    return gate, doc


async def _session_snapshot(db: AsyncDatabase, settings: Settings, ctx: AuthContext) -> Snapshot:
    """One validated JPEG from the session's gate camera (one request per camera at a time)."""
    found = await session_camera(db, settings, ctx)
    if found is None:
        raise UNAVAILABLE_AT_GATE
    gate, _ = found
    lock = _testing.setdefault(gate["_id"], asyncio.Lock())
    if lock.locked():
        raise CAMERA_BUSY
    async with lock:
        try:
            client = await client_for(db, settings, gate["_id"])
        except AppError:                                  # key missing / password unreadable: admin wording
            raise UNUSABLE_AT_GATE from None
        try:
            return await asyncio.to_thread(client.capture_snapshot)
        except CameraError as e:
            raise AppError(502, e.code.value.lower(), e.message) from None


async def preview_for_session(db: AsyncDatabase, settings: Settings, ctx: AuthContext) -> Snapshot:
    """One live-view frame from the session's gate camera, exactly as the camera sent it. Only for
    showing the guard what the camera sees; never uploaded or stored."""
    return await _session_snapshot(db, settings, ctx)


async def capture_for_session(db: AsyncDatabase, settings: Settings, ctx: AuthContext) -> NormalizedPhoto:
    """One picture from the session's gate camera, checked and scaled like a visitor photo (so the
    upload that follows accepts it), returned as a preview. Nothing is stored here."""
    shot = await _session_snapshot(db, settings, ctx)
    try:
        return await asyncio.to_thread(normalize_photo, shot.data)
    except InvalidImageError:
        raise AppError(502, "camera_image_unusable",
                       "The gate camera's picture cannot be used. Use the webcam and tell the administrator.") \
            from None


async def _run_test(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta, gate_id: str,
                    kind: str) -> CameraTestResult:
    gate = await directory_svc.get(db, directory_svc.GATE, gate_id)
    lock = _testing.setdefault(gate["_id"], asyncio.Lock())
    if lock.locked():
        raise BUSY
    async with lock:
        client = await client_for(db, settings, gate["_id"])
        now = datetime.now(UTC)
        try:
            if kind == "connection":
                device = await asyncio.to_thread(client.get_device_info)
                result = CameraTestResult(ok=True, tested_at=now, device=device)
            else:
                shot = await asyncio.to_thread(client.capture_snapshot)
                try:
                    photo = await asyncio.to_thread(normalize_photo, shot.data)
                except InvalidImageError as e:           # e.g. more pixels than the VMS accepts
                    result = CameraTestResult(ok=False, tested_at=now, code="CAMERA_IMAGE_UNUSABLE", message=str(e),
                                        camera_size=(shot.width, shot.height))
                else:
                    result = CameraTestResult(ok=True, tested_at=now, photo=photo,
                                              camera_size=(shot.width, shot.height))
        except CameraError as e:
            result = CameraTestResult(ok=False, tested_at=now, code=e.code.value, message=e.message)

        if kind == "connection":
            last = {"at": now, "ok": result.ok, "code": result.code, "message": result.message}
            if result.device:
                last.update(model=result.device.model, firmware=result.device.firmware,
                            device_name=result.device.device_name)
            await db.settings.update_one({"_id": doc_id(gate["_id"])}, {"$set": {"last_test": last}})
        await audit.record(db, AuditAction.GATE_CAMERA_TESTED, result="SUCCESS" if result.ok else "FAILURE",
                           actor=actor_from_user(ctx.user), ip=meta.ip, resource_type="gates",
                           resource_id=gate["_id"], metadata={"test": kind, "code": result.code})
        return result


async def test_connection(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
                          gate_id: str) -> CameraTestResult:
    """Device information with the saved settings: reachable, login accepted, model and firmware."""
    return await _run_test(db, settings, ctx, meta, gate_id, "connection")


async def test_photo(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
                     gate_id: str) -> CameraTestResult:
    """One snapshot, checked like a visitor photo and returned. Nothing is stored."""
    return await _run_test(db, settings, ctx, meta, gate_id, "photo")
