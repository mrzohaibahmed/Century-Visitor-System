"""SQL Server access for the directory tables: gates, departments and hosts (queries only)."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import insert as sql_insert
from sqlalchemy import select, true, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error
from app.repositories.rows import as_doc, like_prefix, new_row

COLLECTIONS = {"gates": tables.gates, "departments": tables.departments, "hosts": tables.hosts}


def _table(name: str):
    if name not in COLLECTIONS:
        raise ValueError(f"not a directory collection: {name}")
    return COLLECTIONS[name]


async def find_by_id(db: SqlDb, collection: str, item_id: UUID,
                     session: AsyncConnection | None = None) -> dict | None:
    table = _table(collection)
    async with connection(db, session) as conn:
        return as_doc((await conn.execute(select(table).where(table.c.id == item_id))).first())


async def list_items(db: SqlDb, collection: str, *, include_inactive: bool, limit: int,
                     name_search_prefix: str | None = None, by_department: bool = False,
                     department_id: UUID | None = None) -> list[dict]:
    """Gates and departments sort by name (ignoring case); hosts by their search key.
    Host filters: `name_search_prefix`, and with `by_department` the hosts whose department is
    `department_id` (None: hosts without a department)."""
    table = _table(collection)
    query = select(table)
    if not include_inactive:
        query = query.where(table.c.is_active == true())
    if name_search_prefix:
        # Exact (case-sensitive) prefix, as MongoDB's ^prefix regex: name_search is binary (migration 0004).
        query = query.where(table.c.name_search.like(like_prefix(name_search_prefix), escape="\\"))
    if by_department:
        query = query.where(table.c.department_id == department_id if department_id is not None
                            else table.c.department_id.is_(None))
    if collection == "hosts":
        query = query.order_by(table.c.name_search, table.c.id)          # binary: exact order
    else:
        query = query.order_by(table.c.name, table.c.id)        # the column's collation ignores case
    async with connection(db) as conn:
        return [as_doc(row) for row in await conn.execute(query.limit(limit))]


async def names_by_id(db: SqlDb, collection: str, ids: set[UUID]) -> dict[UUID, str]:
    if not ids:
        return {}
    table = _table(collection)
    async with connection(db) as conn:
        rows = await conn.execute(select(table.c.id, table.c.name).where(table.c.id.in_(list(ids))))
        return {row.id: row.name for row in rows}


async def insert(db: SqlDb, collection: str, doc: dict, session: AsyncConnection | None = None) -> UUID:
    """Raises DuplicateKey for a gate or department name that already exists (ignoring case). Sets doc["_id"]."""
    table = _table(collection)
    row = new_row(table, doc)
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(sql_insert(table), row)
    return doc["_id"]


async def update_fields(db: SqlDb, collection: str, item_id: UUID, fields: dict,
                        session: AsyncConnection | None = None) -> None:
    """Sets `fields` and updated_at. Raises DuplicateKey for a name that already exists."""
    table = _table(collection)
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(update(table).where(table.c.id == item_id)
                               .values(**fields, updated_at=datetime.now(UTC)))
