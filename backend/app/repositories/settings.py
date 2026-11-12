"""
SQL Server access for the settings stored under a fixed key:

    "email_smtp"            -> dbo.email_settings (a single row)
    "gate_camera:<gate id>" -> dbo.gate_cameras (one row per gate)

Documents come back as dictionaries: "_id" is the key, the sealed password (core/secrets) is
"password": {"v", "kid", "nonce", "ct"} (absent when none is saved), a camera's last connection test is
"last_test" (absent when there is none) and a camera document carries "type": "gate_camera".
"""
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete as sql_delete
from sqlalchemy import insert as sql_insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import ids, tables
from app.repositories.connection import connection
from app.repositories.rows import checked

EMAIL_KEY = "email_smtp"
CAMERA_PREFIX = "gate_camera:"
PASSWORD = ("version", "kid", "nonce", "ct")
LAST_TEST = ("at", "ok", "code", "message", "model", "firmware", "device_name")


def _where(key: str):
    """(table, condition, the identifying columns for an insert) for a settings key."""
    if key == EMAIL_KEY:
        return tables.email_settings, tables.email_settings.c.id == 1, {"id": 1}
    if key.startswith(CAMERA_PREFIX):
        gate_id = ids.to_id(key[len(CAMERA_PREFIX):])
        return tables.gate_cameras, tables.gate_cameras.c.gate_id == gate_id, {"gate_id": gate_id}
    raise ValueError(f"unknown settings key: {key}")


def _doc(key: str, row) -> dict | None:
    if row is None:
        return None
    m = dict(row._mapping)
    doc: dict = {"_id": key}
    if key.startswith(CAMERA_PREFIX):
        doc["type"] = "gate_camera"
    sealed = {name: m.pop(f"password_{name}") for name in PASSWORD}
    if sealed["ct"] is not None:
        doc["password"] = {"v": sealed["version"], "kid": sealed["kid"], "nonce": bytes(sealed["nonce"]),
                           "ct": bytes(sealed["ct"])}
    if "last_test_at" in m:
        test = {name: m.pop(f"last_test_{name}") for name in LAST_TEST}
        if test["at"] is not None:
            doc["last_test"] = {name: value for name, value in test.items()
                                if value is not None or name in ("at", "ok", "code", "message")}
    m.pop("id", None)
    return doc | m


def _columns(table, fields: dict, remove: Iterable[str] = ()) -> dict:
    """Document fields -> columns (the sealed password and last test flattened; "type" is implied)."""
    columns = {key: value for key, value in fields.items() if key not in ("type", "password", "last_test", "_id")}
    if "password" in fields or "password" in remove:
        sealed = fields.get("password") or {}
        columns |= {f"password_{name}": sealed.get("v" if name == "version" else name) for name in PASSWORD}
    if "last_test" in fields or "last_test" in remove:
        test = fields.get("last_test") or {}
        columns |= {f"last_test_{name}": test.get(name) for name in LAST_TEST}
    return checked(table, columns)


async def get(db: SqlDb, key: str, session: AsyncConnection | None = None) -> dict | None:
    """The document stored under `key`, or None."""
    table, where, _ = _where(key)
    async with connection(db, session) as conn:
        return _doc(key, (await conn.execute(select(table).where(where))).first())


async def get_many(db: SqlDb, keys: list[str]) -> list[dict]:
    found = []
    for key in keys:
        doc = await get(db, key)
        if doc is not None:
            found.append(doc)
    return found


async def upsert(db: SqlDb, key: str, fields: dict, *, now: datetime, remove: Iterable[str] = (),
                 session: AsyncConnection | None = None) -> None:
    """Sets `fields` on the document under `key` (created with created_at=now if missing) and removes the
    fields named in `remove`. Fields not mentioned are kept."""
    remove = list(remove)
    table, where, identity = _where(key)
    values = _columns(table, fields, remove)
    async with connection(db, session) as conn:
        result = await conn.execute(update(table).where(where).values(**values))
        if result.rowcount == 0:
            await conn.execute(sql_insert(table), {**values, **identity, "created_at": now})


async def set_fields(db: SqlDb, key: str, fields: dict) -> None:
    """Sets `fields` on an existing document (nothing happens if there is none)."""
    table, where, _ = _where(key)
    async with connection(db) as conn:
        await conn.execute(update(table).where(where).values(**_columns(table, fields)))


async def delete(db: SqlDb, key: str, session: AsyncConnection | None = None) -> bool:
    """True if a document was deleted."""
    table, where, _ = _where(key)
    async with connection(db, session) as conn:
        return (await conn.execute(sql_delete(table).where(where))).rowcount > 0
