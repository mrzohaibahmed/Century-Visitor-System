"""
Visitor photos.

Storage: a private folder on the API server (settings.photo_dir), outside the
web application. Each file gets a random 128-bit name; the `photos` collection
holds that name and the metadata. The file name, the folder and the path are
never returned by the API: photos are only reachable through GET /photos/{id},
which checks the caller's permission on every request.

Who may see which photo:
- administrators (photo:view_all): any photo;
- guards (photo:view): only photos needed at the gate, i.e. a visitor's
  current photo (identity check at check-in) or the photo of a visit that is
  still inside (identity check at check-out). Earlier photos are refused.

Retention: nothing is deleted automatically yet. captured_at is indexed so a
retention clean-up can be added in production hardening.
"""
import asyncio
import hashlib
import logging
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings
from app.core.errors import AppError
from app.core.images import InvalidImageError, normalize_photo
from app.core.permissions import Permission, has_permission
from app.db.transactions import run_in_transaction
from app.services import audit
from app.services import visitors as visitors_svc
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta, session_gate

log = logging.getLogger(__name__)

NOT_FOUND = AppError(404, "not_found", "Photo not found.")


def _oid(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    if not ObjectId.is_valid(value):
        raise NOT_FOUND
    return ObjectId(value)


def _path(settings: Settings, storage_key: str) -> Path:
    # Two-character sub-folders keep any one folder small. storage_key is 32 hex characters
    # generated here (validated by the collection schema), so it cannot escape photo_dir.
    return settings.photo_dir / storage_key[:2] / f"{storage_key}.jpg"


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)              # never leaves a half-written photo under its final name


def _read_file(path: Path) -> bytes:
    return path.read_bytes()


async def capture(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
                  visitor_id: str, data: bytes) -> dict:
    """Validates and stores a new photo and makes it the visitor's current photo."""
    visitor = await visitors_svc.get(db, visitor_id)
    try:
        photo = await asyncio.to_thread(normalize_photo, data)
    except InvalidImageError as e:
        raise AppError(422, "invalid_photo", str(e)) from None

    gate, _ = await session_gate(db, ctx.session)
    now = datetime.now(UTC)
    doc = {
        "storage_key": secrets.token_hex(16), "visitor_id": visitor["_id"], "visit_id": None,
        "content_type": photo.content_type, "size_bytes": len(photo.data), "width": photo.width,
        "height": photo.height, "sha256": hashlib.sha256(photo.data).hexdigest(),
        "captured_by": ctx.user["_id"], "captured_at": now, "gate_id": gate["_id"] if gate else None,
    }
    path = _path(settings, doc["storage_key"])
    await asyncio.to_thread(_write_file, path, photo.data)

    async def work(s: AsyncClientSession):
        doc["_id"] = (await db.photos.insert_one(doc, session=s)).inserted_id
        await db.visitors.update_one({"_id": visitor["_id"]},
                                     {"$set": {"current_photo_id": doc["_id"], "updated_at": now}}, session=s)
        await audit.record(db, AuditAction.PHOTO_CAPTURED, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type="visitor", resource_id=visitor["_id"],
                           metadata={"photo_id": doc["_id"], "size_bytes": doc["size_bytes"],
                                     "gate_id": doc["gate_id"]}, session=s)

    try:
        await run_in_transaction(db, work)
    except Exception:
        await asyncio.to_thread(path.unlink, True)          # no orphan file without a record
        raise
    return doc


async def for_check_in(db: AsyncDatabase, visitor: dict, photo_id: str) -> ObjectId:
    """The photo a check-in refers to must be this visitor's current photo."""
    oid = _oid(photo_id)
    if visitor.get("current_photo_id") != oid:
        raise AppError(422, "invalid_photo", "The photo does not belong to this visitor. Please take it again.")
    return oid


async def _guard_may_view(db: AsyncDatabase, photo: dict) -> bool:
    if await db.visitors.count_documents({"_id": photo["visitor_id"], "current_photo_id": photo["_id"]}, limit=1):
        return True
    return bool(await db.visits.count_documents({"photo_id": photo["_id"], "status": "CHECKED_IN"}, limit=1))


async def read(db: AsyncDatabase, settings: Settings, ctx: AuthContext, meta: RequestMeta,
               photo_id: str) -> tuple[bytes, str]:
    photo = await db.photos.find_one({"_id": _oid(photo_id)})
    if photo is None:
        raise NOT_FOUND
    if not has_permission(ctx.user.get("role"), Permission.PHOTO_VIEW_ALL) and not await _guard_may_view(db, photo):
        await audit.record(db, AuditAction.ACCESS_DENIED, result="DENIED", actor=actor_from_user(ctx.user),
                           ip=meta.ip, resource_type="photo", resource_id=photo["_id"],
                           metadata={"reason": "photo_not_needed_at_gate"})
        raise AppError(403, "forbidden", "You do not have permission to view this photo.")
    try:
        data = await asyncio.to_thread(_read_file, _path(settings, photo["storage_key"]))
    except FileNotFoundError:
        log.error("Photo file missing for photo %s", photo["_id"])        # id only; never the path
        raise NOT_FOUND from None
    return data, photo["content_type"]
