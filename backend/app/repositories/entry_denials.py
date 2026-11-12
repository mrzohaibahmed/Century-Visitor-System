"""SQL Server access for refused entries (reporting only; never part of the security decision)."""
import asyncio
from uuid import UUID

from sqlalchemy import insert as sql_insert
from sqlalchemy import select

from app.db.sql.database import SqlDb
from app.repositories import tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error
from app.repositories.rows import new_row

entry_denials = tables.entry_denials


async def insert(db: SqlDb, doc: dict) -> None:
    """Raises DuplicateKey if this source audit entry is already recorded. Other database errors are
    raised unchanged (see errors.DATABASE_ERRORS). Sets doc["_id"].

    The caller writes this under a time limit (services/entry_denials). The insert itself is shielded: if
    the limit cancels the caller, the insert still finishes on its own connection. Cancelling a driver call
    in the middle would close the connection under a thread that is still using it."""
    row = new_row(entry_denials, doc)

    async def write() -> None:
        with duplicates_as_domain_error():
            async with connection(db) as conn:
                await conn.execute(sql_insert(entry_denials), row)

    await asyncio.shield(write())


async def insert_if_absent(db: SqlDb, source_audit_id: UUID, doc: dict) -> bool:
    """Creates the document for this audit entry unless one exists (an existing one is never changed).
    True if it was created. Raises DuplicateKey when a concurrent run created it at the same moment."""
    exists = select(entry_denials.c.id).where(entry_denials.c.source_audit_id == source_audit_id)
    async with connection(db) as conn:
        if (await conn.execute(exists)).first() is not None:
            return False
    row = new_row(entry_denials, {**doc, "source_audit_id": source_audit_id})
    with duplicates_as_domain_error():
        async with connection(db) as conn:
            await conn.execute(sql_insert(entry_denials), row)
    return True
