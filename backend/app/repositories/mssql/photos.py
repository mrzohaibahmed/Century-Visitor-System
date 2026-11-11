"""SQL Server access for photo metadata (the image files themselves live in CG_PHOTO_DIR).
Same functions as mongo/photos.py."""
from uuid import UUID

from sqlalchemy import insert as sql_insert
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories.mssql import tables
from app.repositories.mssql.connection import connection
from app.repositories.mssql.rows import as_doc, new_row

photos = tables.photos


async def find_by_id(db: SqlDb, photo_id: UUID) -> dict | None:
    async with connection(db) as conn:
        return as_doc((await conn.execute(select(photos).where(photos.c.id == photo_id))).first())


async def link_first_visit(db: SqlDb, photo_id: UUID, visit_id: UUID, session: AsyncConnection | None = None) -> None:
    """Records the visit where the photo was taken (only once: a later visit may reuse the photo)."""
    async with connection(db, session) as conn:
        await conn.execute(update(photos).where(photos.c.id == photo_id, photos.c.visit_id.is_(None))
                           .values(visit_id=visit_id))


async def insert(db: SqlDb, doc: dict, session: AsyncConnection | None = None) -> UUID:
    """Sets doc["_id"]."""
    row = new_row(photos, doc)
    async with connection(db, session) as conn:
        await conn.execute(sql_insert(photos), row)
    return doc["_id"]
