"""
Gates, departments and hosts (admin-managed reference data).

Entries are deactivated, never deleted, so old visits keep pointing at a real
record. Names of gates and departments are unique regardless of case.
"""
from dataclasses import dataclass
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase

from app.core.errors import AppError
from app.core.identity import search_key
from app.db.transactions import run_in_transaction
from app.repositories import directory as directory_repo
from app.repositories import gates as gates_repo
from app.repositories import users as users_repo
from app.repositories.errors import DuplicateKey
from app.repositories.ids import is_id, parse_id
from app.services import audit
from app.services.audit import AuditAction, actor_from_user
from app.services.auth import AuthContext, RequestMeta


@dataclass(frozen=True)
class Kind:
    collection: str
    label: str
    created: AuditAction
    updated: AuditAction
    unique_name: bool


GATE = Kind("gates", "Gate", AuditAction.GATE_CREATED, AuditAction.GATE_UPDATED, True)
DEPARTMENT = Kind("departments", "Department", AuditAction.DEPARTMENT_CREATED, AuditAction.DEPARTMENT_UPDATED, True)
HOST = Kind("hosts", "Host", AuditAction.HOST_CREATED, AuditAction.HOST_UPDATED, False)

MAX_LIST = 500


_oid = parse_id


async def get(db: AsyncDatabase, kind: Kind, item_id: str | ObjectId, session: AsyncClientSession | None = None
              ) -> dict:
    oid = _oid(item_id)
    doc = await directory_repo.find_by_id(db, kind.collection, oid, session=session) if oid else None
    if doc is None:
        raise AppError(404, "not_found", f"{kind.label} not found.")
    return doc


async def get_active(db: AsyncDatabase, kind: Kind, item_id: str | ObjectId,
                     session: AsyncClientSession | None = None) -> dict:
    doc = await get(db, kind, item_id, session=session)
    if not doc.get("is_active"):
        raise AppError(409, "inactive", f"{kind.label} '{doc['name']}' is no longer active.")
    return doc


async def list_items(db: AsyncDatabase, kind: Kind, *, include_inactive: bool = False, q: str | None = None,
                     department_id: str | None = None) -> list[dict]:
    is_host = kind is HOST
    prefix = search_key(q) if is_host and q else None
    by_department = bool(is_host and department_id)
    # An invalid department_id is passed on as None (hosts without a department), as before.
    return await directory_repo.list_items(
        db, kind.collection, include_inactive=include_inactive, limit=MAX_LIST, name_search_prefix=prefix,
        by_department=by_department, department_id=_oid(department_id) if by_department else None)


async def department_names(db: AsyncDatabase, ids: set[ObjectId]) -> dict[ObjectId, str]:
    return await directory_repo.names_by_id(db, DEPARTMENT.collection, ids)


async def _validate_department(db: AsyncDatabase, fields: dict, s: AsyncClientSession) -> None:
    if fields.get("department_id") is not None:
        fields["department_id"] = (await get_active(db, DEPARTMENT, fields["department_id"], session=s))["_id"]


async def _validate_linked_user(db: AsyncDatabase, fields: dict, s: AsyncClientSession) -> None:
    """A host's "Linked app account" must be an existing, active Admin/Guard user."""
    if fields.get("linked_user_id") is not None:
        oid = _oid(fields["linked_user_id"])
        user_id = await users_repo.find_active_id(db, oid, session=s) if oid else None
        if user_id is None:
            raise AppError(422, "invalid_linked_user", "Choose an active app account to link to this host.")
        fields["linked_user_id"] = user_id


async def user_names(db: AsyncDatabase, ids: set[ObjectId]) -> dict[ObjectId, str]:
    return await users_repo.display_names(db, ids)


async def create(db: AsyncDatabase, kind: Kind, ctx: AuthContext, meta: RequestMeta, data: dict) -> dict:
    now = datetime.now(UTC)
    doc = {k: v for k, v in data.items() if v is not None}
    doc.update({"is_active": True, "created_at": now, "updated_at": now, "created_by": ctx.user["_id"]})
    if kind is HOST:
        doc["name_search"] = search_key(doc["name"])

    async def work(s: AsyncClientSession):
        if kind is HOST:
            await _validate_department(db, doc, s)
            await _validate_linked_user(db, doc, s)
        doc["_id"] = await directory_repo.insert(db, kind.collection, doc, session=s)
        await audit.record(db, kind.created, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type=kind.collection, resource_id=doc["_id"],
                           changes={k: _plain(v) for k, v in data.items() if v is not None}, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKey:
        raise AppError(409, "name_taken", f"A {kind.label.lower()} named '{data['name']}' already exists.") from None
    return doc


async def update(db: AsyncDatabase, kind: Kind, ctx: AuthContext, meta: RequestMeta, item_id: str,
                 changes: dict) -> dict:
    current = await get(db, kind, item_id)
    clear_linked_user = changes.pop("clear_linked_user", None)
    fields = {k: v for k, v in changes.items() if v is not None and v != current.get(k)}
    for key in ("department_id", "linked_user_id"):
        if changes.get(key) is not None and _oid(changes[key]) != current.get(key):
            fields[key] = changes[key]
        elif changes.get(key) is not None:
            fields.pop(key, None)                      # unchanged
    if clear_linked_user and current.get("linked_user_id") is not None:
        fields["linked_user_id"] = None
    if not fields:
        return current
    if kind is HOST and "name" in fields:
        fields["name_search"] = search_key(fields["name"])

    async def work(s: AsyncClientSession):
        if kind is HOST:
            await _validate_department(db, fields, s)
            await _validate_linked_user(db, fields, s)
        await directory_repo.update_fields(db, kind.collection, current["_id"], fields, session=s)
        diff = {k: {"from": _plain(current.get(k)), "to": _plain(v)} for k, v in fields.items() if k != "name_search"}
        await audit.record(db, kind.updated, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type=kind.collection, resource_id=current["_id"], changes=diff, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKey:
        raise AppError(409, "name_taken", f"A {kind.label.lower()} with that name already exists.") from None
    return await get(db, kind, current["_id"])


def _plain(value):
    return str(value) if is_id(value) else value


async def active_gate_ids(db: AsyncDatabase) -> list[ObjectId]:
    return await gates_repo.active_ids(db, limit=2)
