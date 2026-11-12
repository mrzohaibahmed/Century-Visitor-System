"""SQL Server access for visitors (queries only; matching rules and normalisation live in services).
Visitors come back as documents: the document under "identity"."""
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, or_, select, update
from sqlalchemy import insert as sql_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error
from app.repositories.rows import as_doc, checked, identity_columns, like_prefix, new_row, with_identity

visitors = tables.visitors
NAME_ORDER = (visitors.c.name_search, visitors.c.id)          # name_search is binary: exact order


def visitor_doc(row) -> dict | None:
    return with_identity(as_doc(row)) if row is not None else None


def _identity_or_phone(identities: list[tuple[str, str]], phone: str | None) -> list:
    clauses = [and_(visitors.c.identity_type == kind, visitors.c.identity_number == number)
               for kind, number in identities]
    if phone:
        clauses.append(visitors.c.phone == phone)
    return clauses


def _prefix(name_prefix: str):
    return visitors.c.name_search.like(like_prefix(name_prefix), escape="\\")


async def find_by_id(db: SqlDb, visitor_id: UUID, session: AsyncConnection | None = None) -> dict | None:
    async with connection(db, session) as conn:
        return visitor_doc((await conn.execute(select(visitors).where(visitors.c.id == visitor_id))).first())


async def find_by_identity(db: SqlDb, id_type: str, number: str) -> dict | None:
    """The visitor with exactly this (already normalised) document."""
    query = select(visitors).where(visitors.c.identity_type == id_type, visitors.c.identity_number == number)
    async with connection(db) as conn:
        return visitor_doc((await conn.execute(query)).first())


async def find_exact(db: SqlDb, identities: list[tuple[str, str]], phone: str | None, limit: int) -> list[dict]:
    """Visitors with any of these documents or this phone number, in name order."""
    clauses = _identity_or_phone(identities, phone)
    if not clauses:
        return []
    query = select(visitors).where(or_(*clauses)).order_by(*NAME_ORDER).limit(limit)
    async with connection(db) as conn:
        return [visitor_doc(row) for row in await conn.execute(query)]


async def list_by_name(db: SqlDb, *, name_prefix: str | None, after: tuple[str, UUID] | None,
                       limit: int) -> list[dict]:
    """Name order (search key, then ID). `after`: the (search key, ID) of the last row already shown."""
    query = select(visitors)
    if name_prefix is not None:
        query = query.where(_prefix(name_prefix))
    if after:
        last_name, last_id = after
        query = query.where(or_(visitors.c.name_search > last_name,
                                and_(visitors.c.name_search == last_name, visitors.c.id > last_id)))
    async with connection(db) as conn:
        return [visitor_doc(row) for row in await conn.execute(query.order_by(*NAME_ORDER).limit(limit))]


async def matching_ids(db: SqlDb, *, name_prefix: str, identities: list[tuple[str, str]],
                       phone: str | None, limit: int) -> list[UUID]:
    """IDs of visitors whose name starts with `name_prefix` or who have one of these documents or this phone."""
    query = select(visitors.c.id).where(or_(_prefix(name_prefix), *_identity_or_phone(identities, phone)))
    async with connection(db) as conn:
        return list((await conn.execute(query.order_by(visitors.c.id).limit(limit))).scalars())


async def has_current_photo(db: SqlDb, visitor_id: UUID, photo_id: UUID) -> bool:
    query = select(visitors.c.id).where(visitors.c.id == visitor_id, visitors.c.current_photo_id == photo_id)
    async with connection(db) as conn:
        return (await conn.execute(query)).first() is not None


async def insert(db: SqlDb, doc: dict, session: AsyncConnection | None = None) -> UUID:
    """Raises DuplicateKey if a visitor with this document already exists. Sets doc["_id"]."""
    row = new_row(visitors, doc, identity_columns(doc))
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(sql_insert(visitors), row)
    return doc["_id"]


async def update_fields(db: SqlDb, visitor_id: UUID, fields: dict, session: AsyncConnection | None = None, *,
                        now: datetime | None = None) -> None:
    """Sets `fields` and updated_at (default: now). Raises DuplicateKey for a document already registered."""
    values = checked(visitors, identity_columns(fields) | {"updated_at": now or datetime.now(UTC)})
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(update(visitors).where(visitors.c.id == visitor_id).values(**values))
