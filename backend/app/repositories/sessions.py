"""SQL Server access for server-side sessions."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import insert as sql_insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import tables
from app.repositories.connection import connection
from app.repositories.rows import as_doc, new_row

sessions = tables.sessions


async def insert(db: SqlDb, doc: dict) -> UUID:
    row = new_row(sessions, doc)
    async with connection(db) as conn:
        await conn.execute(sql_insert(sessions), row)
    return doc["_id"]


async def find_active_by_token_hash(db: SqlDb, token_hash: str) -> dict | None:
    query = select(sessions).where(sessions.c.token_hash == token_hash, sessions.c.revoked_at.is_(None))
    async with connection(db) as conn:
        return as_doc((await conn.execute(query)).first())


async def touch(db: SqlDb, session_id: UUID, now: datetime) -> None:
    async with connection(db) as conn:
        await conn.execute(update(sessions).where(sessions.c.id == session_id).values(last_seen_at=now))


async def set_gate(db: SqlDb, session_id: UUID, gate_id: UUID) -> None:
    async with connection(db) as conn:
        await conn.execute(update(sessions).where(sessions.c.id == session_id).values(gate_id=gate_id))


async def revoke(db: SqlDb, session_id: UUID, reason: str) -> None:
    async with connection(db) as conn:
        await conn.execute(update(sessions).where(sessions.c.id == session_id, sessions.c.revoked_at.is_(None))
                           .values(revoked_at=datetime.now(UTC), revoked_reason=reason))


async def revoke_all_for_user(db: SqlDb, user_id: UUID, reason: str, *, except_session_id: UUID | None = None,
                              session: AsyncConnection | None = None) -> int:
    query = update(sessions).where(sessions.c.user_id == user_id, sessions.c.revoked_at.is_(None))
    if except_session_id is not None:
        query = query.where(sessions.c.id != except_session_id)
    async with connection(db, session) as conn:
        result = await conn.execute(query.values(revoked_at=datetime.now(UTC), revoked_reason=reason))
    return result.rowcount
