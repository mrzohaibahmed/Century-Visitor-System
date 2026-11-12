"""
SQL Server access for the append-only audit trail. Deliberately insert-only: no update or delete.
Entries come back as documents (actor and resource as
sub-dictionaries, changes and metadata only when recorded).

changes / metadata are stored as JSON (json_values.py: IDs and times inside keep their type), so a reader
(e.g. backfill-entry-denials) gets back exactly what was recorded, as from MongoDB.
"""
from collections.abc import AsyncIterator

from sqlalchemy import insert as sql_insert
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import ids, tables
from app.repositories.connection import connection
from app.repositories.json_values import from_json, to_json

audit_logs = tables.audit_logs


def _resource_id_text(value) -> str | None:
    return None if value is None else str(value)


def _resource_id(text: str | None):
    """A recorded GUID comes back as an ID; a key such as "email_smtp" as text."""
    return ids.parse_id(text) or text if text is not None else None


def entry_doc(row) -> dict:
    """A row as the entry audit.record() wrote (the MongoDB document shape)."""
    entry = {
        "_id": row.id, "timestamp": row.timestamp, "action": row.action, "result": row.result,
        "actor": {"user_id": row.actor_user_id, "username": row.actor_username, "role": row.actor_role},
        "resource": {"type": row.resource_type, "id": _resource_id(row.resource_id)},
        "ip": row.ip, "request_id": row.request_id,
    }
    if row.changes is not None:
        entry["changes"] = from_json(row.changes)
    if row.metadata is not None:
        entry["metadata"] = from_json(row.metadata)
    return entry


def entry_columns(entry: dict) -> dict:
    """An entry (the shape audit.record() writes) as the columns of its row, without the id."""
    actor = entry.get("actor") or {}
    resource = entry.get("resource") or {}
    return {
        "timestamp": entry["timestamp"], "action": entry["action"], "result": entry["result"],
        "actor_user_id": actor.get("user_id"), "actor_username": actor.get("username"),
        "actor_role": actor.get("role"),
        "resource_type": resource.get("type"), "resource_id": _resource_id_text(resource.get("id")),
        "ip": entry.get("ip"), "request_id": entry.get("request_id"),
        "changes": to_json(entry.get("changes")), "metadata": to_json(entry.get("metadata")),
    }


async def insert(db: SqlDb, entry: dict, session: AsyncConnection | None = None) -> None:
    """Inserts the entry and sets entry["_id"]."""
    entry["_id"] = ids.new_id()
    row = {"id": entry["_id"], **entry_columns(entry)}
    async with connection(db, session) as conn:
        await conn.execute(sql_insert(audit_logs), row)


async def iter_by_action(db: SqlDb, action: str) -> AsyncIterator[dict]:
    """Every entry with this action, oldest first (insertion order)."""
    query = select(audit_logs).where(audit_logs.c.action == action).order_by(audit_logs.c.id)
    async with connection(db) as conn:
        rows = (await conn.execute(query)).all()
    for row in rows:
        yield entry_doc(row)
