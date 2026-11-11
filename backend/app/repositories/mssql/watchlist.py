"""
SQL Server access for the watchlist (queries only; identity normalisation and rules live in services).
Same functions as mongo/watchlist.py; entries come back as before (the document under "identity").

"OTHER" numbers were matched with a MongoDB regex that ignores spaces, / and - (^OTHER:A[ /-]*B[ /-]*C$).
SQL Server has no regex, so the same rule is written out: the stored identifier without those separators
(identifier_compact, a computed and indexed column) equals "OTHER:" + the number's letters and digits, and
the number starts and ends with a letter or digit (the regex allowed no separator before the first or
after the last character).
"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, false, func, or_, select, true, update
from sqlalchemy import insert as sql_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories.mssql import tables
from app.repositories.mssql.connection import connection
from app.repositories.mssql.errors import duplicates_as_domain_error
from app.repositories.mssql.rows import as_doc, checked, identity_columns, like_prefix, new_row, with_identity
from app.schemas.watchlist import WatchlistStatus

watchlist = tables.watchlist
BINARY = "Latin1_General_100_BIN2"
NEWEST_FIRST = (watchlist.c.created_at.desc(), watchlist.c.id.desc())
_ACTIVE = watchlist.c.is_active == true()


def entry_doc(row) -> dict | None:
    if row is None:
        return None
    doc = with_identity(as_doc(row))
    doc.pop("identifier_compact", None)            # computed by SQL Server; not part of the entry
    return doc


def _exactly_one_of(identifiers: list[str]):
    """identifier is one of these, byte for byte (also its length: 'X ' is not 'X')."""
    exact = watchlist.c.identifier.collate(BINARY)
    return or_(false(), *(and_(exact == value,
                               func.datalength(watchlist.c.identifier) == len(value.encode("utf-16-le")))
                          for value in identifiers))      # NVARCHAR stores UTF-16


def _not_expired(now: datetime):
    return or_(watchlist.c.expires_at.is_(None), watchlist.c.expires_at > now)


def _status(status: WatchlistStatus | None, now: datetime):
    if status is WatchlistStatus.ACTIVE:
        return and_(_ACTIVE, _not_expired(now))
    if status is WatchlistStatus.EXPIRED:
        return and_(_ACTIVE, watchlist.c.expires_at <= now)
    if status is WatchlistStatus.DISABLED:
        return watchlist.c.is_active == false()
    return None


async def find_active_match(db: SqlDb, identifiers: list[str], other_compact: str | None,
                            now: datetime) -> dict | None:
    """The active, unexpired entry whose identifier is one of `identifiers`, or (with `other_compact`) an
    "OTHER:" identifier equal to `other_compact` when spaces, / and - are ignored."""
    # Each condition twice: as the column compares (uses the index) and exactly as MongoDB compared:
    # case-sensitive (binary collation), [0-9A-Z] as plain characters (not linguistic ranges), and trailing
    # spaces significant (SQL Server's = and LIKE ignore them; byte lengths and character codes do not).
    clauses = [and_(watchlist.c.identifier.in_(identifiers), _exactly_one_of(identifiers))]
    if other_compact:
        compact = f"OTHER:{other_compact}"
        last = func.unicode(func.right(watchlist.c.identifier, 1))
        clauses.append(and_(watchlist.c.identifier_compact == compact,
                            watchlist.c.identifier_compact.collate(BINARY) == compact,
                            watchlist.c.identifier.collate(BINARY).like("OTHER:[0-9A-Z]%"),
                            or_(last.between(48, 57), last.between(65, 90))))     # ends with 0-9 or A-Z
    query = select(watchlist).where(or_(*clauses), _not_expired(now), _ACTIVE).order_by(watchlist.c.id).limit(1)
    async with connection(db) as conn:
        return entry_doc((await conn.execute(query)).first())


async def list_page(db: SqlDb, *, status: WatchlistStatus | None, now: datetime,
                    search_identifiers: list[str] | None, search_name_prefix: str | None,
                    after: tuple[datetime, UUID] | None, limit: int) -> list[dict]:
    """Newest first. With `search_name_prefix` (not None): entries with one of `search_identifiers` or
    a name starting with the prefix. `after`: the (created_at, ID) of the last row already shown."""
    query = select(watchlist)
    by_status = _status(status, now)
    if by_status is not None:
        query = query.where(by_status)
    if search_name_prefix is not None:
        query = query.where(or_(watchlist.c.identifier.in_(search_identifiers or []),
                                watchlist.c.name_search.like(like_prefix(search_name_prefix), escape="\\")))
    if after:
        last_at, last_id = after
        query = query.where(or_(watchlist.c.created_at < last_at,
                                and_(watchlist.c.created_at == last_at, watchlist.c.id < last_id)))
    async with connection(db) as conn:
        return [entry_doc(row) for row in await conn.execute(query.order_by(*NEWEST_FIRST).limit(limit))]


async def find_by_id(db: SqlDb, entry_id: UUID) -> dict | None:
    async with connection(db) as conn:
        return entry_doc((await conn.execute(select(watchlist).where(watchlist.c.id == entry_id))).first())


async def find_active_by_identifier(db: SqlDb, identifier: str,
                                    session: AsyncConnection | None = None) -> dict | None:
    """The entry with is_active (whether or not it has expired) for this identifier; at most one exists."""
    query = select(watchlist).where(watchlist.c.identifier == identifier, _ACTIVE)
    async with connection(db, session) as conn:
        return entry_doc((await conn.execute(query)).first())


async def insert(db: SqlDb, doc: dict, session: AsyncConnection | None = None) -> UUID:
    """Raises DuplicateKey if the identifier already has an is_active entry. Sets doc["_id"]."""
    row = new_row(watchlist, doc, identity_columns(doc))
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(sql_insert(watchlist), row)
    return doc["_id"]


async def update_fields(db: SqlDb, entry_id: UUID, fields: dict, *, only_if_active: bool,
                        session: AsyncConnection | None = None) -> None:
    """Sets exactly `fields` (callers set updated_at/updated_by themselves)."""
    query = update(watchlist).where(watchlist.c.id == entry_id)
    if only_if_active:
        query = query.where(_ACTIVE)
    async with connection(db, session) as conn:
        await conn.execute(query.values(**checked(watchlist, identity_columns(fields))))
