"""
Gates, departments and hosts (admin-managed reference data).

Entries are deactivated, never deleted, so old visits keep pointing at a real
record. Names of gates and departments are unique regardless of case.
"""
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from bson import ObjectId
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import DuplicateKeyError

from app.core.errors import AppError
from app.core.identity import search_key
from app.db.schema import CASE_INSENSITIVE
from app.db.transactions import run_in_transaction
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


def _oid(value: str | ObjectId | None) -> ObjectId | None:
    if value is None or isinstance(value, ObjectId):
        return value
    return ObjectId(value) if ObjectId.is_valid(value) else None


async def get(db: AsyncDatabase, kind: Kind, item_id: str | ObjectId, session: AsyncClientSession | None = None
              ) -> dict:
    oid = _oid(item_id)
    doc = await db[kind.collection].find_one({"_id": oid}, session=session) if oid else None
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
    query: dict = {} if include_inactive else {"is_active": True}
    if kind is HOST:
        if q:
            query["name_search"] = {"$regex": "^" + re.escape(search_key(q))}
        if department_id:
            query["department_id"] = _oid(department_id)
        sort = [("name_search", 1)]
    else:
        sort = [("name", 1)]
    cursor = db[kind.collection].find(query).sort(sort).limit(MAX_LIST)
    if kind is not HOST:
        cursor = cursor.collation(CASE_INSENSITIVE)
    return await cursor.to_list(length=MAX_LIST)


async def department_names(db: AsyncDatabase, ids: set[ObjectId]) -> dict[ObjectId, str]:
    if not ids:
        return {}
    docs = await db.departments.find({"_id": {"$in": list(ids)}}, {"name": 1}).to_list(length=len(ids))
    return {d["_id"]: d["name"] for d in docs}


async def _validate_department(db: AsyncDatabase, fields: dict, s: AsyncClientSession) -> None:
    if fields.get("department_id") is not None:
        fields["department_id"] = (await get_active(db, DEPARTMENT, fields["department_id"], session=s))["_id"]


async def create(db: AsyncDatabase, kind: Kind, ctx: AuthContext, meta: RequestMeta, data: dict) -> dict:
    now = datetime.now(UTC)
    doc = {k: v for k, v in data.items() if v is not None}
    doc.update({"is_active": True, "created_at": now, "updated_at": now, "created_by": ctx.user["_id"]})
    if kind is HOST:
        doc["name_search"] = search_key(doc["name"])

    async def work(s: AsyncClientSession):
        if kind is HOST:
            await _validate_department(db, doc, s)
        doc["_id"] = (await db[kind.collection].insert_one(doc, session=s)).inserted_id
        await audit.record(db, kind.created, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type=kind.collection, resource_id=doc["_id"],
                           changes={k: str(v) if isinstance(v, ObjectId) else v for k, v in data.items()
                                    if v is not None}, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKeyError:
        raise AppError(409, "name_taken", f"A {kind.label.lower()} named '{data['name']}' already exists.") from None
    return doc


async def update(db: AsyncDatabase, kind: Kind, ctx: AuthContext, meta: RequestMeta, item_id: str,
                 changes: dict) -> dict:
    current = await get(db, kind, item_id)
    fields = {k: v for k, v in changes.items() if v is not None and v != current.get(k)}
    if "department_id" in changes and changes["department_id"] is not None:
        fields["department_id"] = changes["department_id"]
    if not fields:
        return current
    if kind is HOST and "name" in fields:
        fields["name_search"] = search_key(fields["name"])

    async def work(s: AsyncClientSession):
        if kind is HOST:
            await _validate_department(db, fields, s)
        await db[kind.collection].update_one(
            {"_id": current["_id"]}, {"$set": {**fields, "updated_at": datetime.now(UTC)}}, session=s)
        diff = {k: {"from": _plain(current.get(k)), "to": _plain(v)} for k, v in fields.items() if k != "name_search"}
        await audit.record(db, kind.updated, actor=actor_from_user(ctx.user), ip=meta.ip,
                           resource_type=kind.collection, resource_id=current["_id"], changes=diff, session=s)

    try:
        await run_in_transaction(db, work)
    except DuplicateKeyError:
        raise AppError(409, "name_taken", f"A {kind.label.lower()} with that name already exists.") from None
    return await get(db, kind, current["_id"])


def _plain(value):
    return str(value) if isinstance(value, ObjectId) else value


async def active_gate_ids(db: AsyncDatabase) -> list[ObjectId]:
    docs = await db.gates.find({"is_active": True}, {"_id": 1}).limit(2).to_list(length=2)
    return [d["_id"] for d in docs]
