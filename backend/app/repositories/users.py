"""SQL Server access for users (queries only; rules live in services)."""
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, literal, select, text, true, update
from sqlalchemy import insert as sql_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import ids, tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error
from app.repositories.rows import as_doc, new_row

users = tables.users
BINARY_ORDER = "Latin1_General_100_BIN2"      # exact (case-sensitive) order, as MongoDB sorted strings
ADMIN_GUARD_TIMEOUT_MS = 10_000


def parse_id(value: str) -> UUID | None:
    # A function here, not an alias: the backend loader only takes names this module defines.
    return ids.parse_id(value)


async def find_by_username(db: SqlDb, username: str) -> dict | None:
    # Case-insensitive, matching the unique index (the column's collation: "Guard1" logs into "guard1").
    async with connection(db) as conn:
        return as_doc((await conn.execute(select(users).where(users.c.username == username))).first())


async def find_by_id(db: SqlDb, user_id: UUID, session: AsyncConnection | None = None) -> dict | None:
    async with connection(db, session) as conn:
        return as_doc((await conn.execute(select(users).where(users.c.id == user_id))).first())


async def any_exist(db: SqlDb) -> bool:
    """Whether any account exists at all."""
    async with connection(db) as conn:
        return (await conn.execute(select(literal(1)).select_from(users).limit(1))).first() is not None


async def list_all(db: SqlDb, limit: int = 500) -> list[dict]:
    """Every account without its password hash, by username."""
    columns = [c for c in users.c if c.name != "password_hash"]
    query = select(*columns).order_by(users.c.username.collate(BINARY_ORDER)).limit(limit)
    async with connection(db) as conn:
        return [as_doc(row) for row in await conn.execute(query)]


async def find_active_id(db: SqlDb, user_id: UUID, session: AsyncConnection | None = None) -> UUID | None:
    """The ID back if that user exists and is active, otherwise None."""
    query = select(users.c.id).where(users.c.id == user_id, users.c.is_active == true())
    async with connection(db, session) as conn:
        return (await conn.execute(query)).scalar_one_or_none()


async def display_names(db: SqlDb, ids: set[UUID]) -> dict[UUID, str]:
    """Display name (or username when it has none) per user ID."""
    if not ids:
        return {}
    query = select(users.c.id, users.c.username, users.c.display_name).where(users.c.id.in_(list(ids)))
    async with connection(db) as conn:
        return {row.id: row.display_name or row.username for row in await conn.execute(query)}


async def insert(db: SqlDb, doc: dict, session: AsyncConnection | None = None) -> UUID:
    """Raises DuplicateKey if the username exists (ignoring case). Sets doc["_id"]."""
    row = new_row(users, doc)
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(sql_insert(users), row)
    return doc["_id"]


async def update_fields(db: SqlDb, user_id: UUID, fields: dict, session: AsyncConnection | None = None) -> None:
    async with connection(db, session) as conn:
        await conn.execute(update(users).where(users.c.id == user_id)
                           .values(**fields, updated_at=datetime.now(UTC)))


async def count_active_admins(db: SqlDb, session: AsyncConnection | None = None) -> int:
    query = select(func.count()).select_from(users).where(users.c.role == "ADMIN", users.c.is_active == true())
    async with connection(db, session) as conn:
        return (await conn.execute(query)).scalar_one()


async def claim_admin_guard(db: SqlDb, session: AsyncConnection) -> None:
    """An exclusive application lock held until the transaction ends. Two transactions that both reduce the
    number of admins therefore run one after the other, and the second counts the admins the first left."""
    result = (await session.execute(text(
        "DECLARE @result INT; "
        "EXEC @result = sp_getapplock @Resource = N'cgvms_admin_guard', @LockMode = 'Exclusive', "
        "@LockOwner = 'Transaction', @LockTimeout = :timeout; "
        "SELECT @result"), {"timeout": ADMIN_GUARD_TIMEOUT_MS})).scalar_one()
    if result < 0:                                   # -1 timeout, -2 cancelled, -3 deadlock victim, -999 error
        raise RuntimeError(f"The administrator change lock could not be taken (sp_getapplock {result}).")


async def record_failed_login(db: SqlDb, user_id: UUID, max_failures: int, lockout_minutes: int) -> bool:
    """Atomic across gate PCs. Returns True if this failure locked the account."""
    async with connection(db) as conn:
        failures = (await conn.execute(
            update(users).where(users.c.id == user_id)
            .values(failed_login_count=users.c.failed_login_count + 1)
            .returning(users.c.failed_login_count))).scalar_one_or_none()
        if failures is not None and failures >= max_failures:
            await conn.execute(update(users).where(users.c.id == user_id).values(
                locked_until=datetime.now(UTC) + timedelta(minutes=lockout_minutes), failed_login_count=0))
            return True
    return False


async def record_successful_login(db: SqlDb, user_id: UUID, new_hash: str | None) -> None:
    fields = {"failed_login_count": 0, "locked_until": None, "last_login_at": datetime.now(UTC)}
    if new_hash:
        fields["password_hash"] = new_hash
    async with connection(db) as conn:
        await conn.execute(update(users).where(users.c.id == user_id).values(**fields))
