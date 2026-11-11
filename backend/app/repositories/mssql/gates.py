"""SQL Server access for gates (queries only; rules live in services). Same functions as mongo/gates.py."""
from uuid import UUID

from sqlalchemy import func, select, true

from app.db.sql.database import SqlDb
from app.repositories.mssql import ids, tables
from app.repositories.mssql.connection import connection
from app.repositories.mssql.rows import as_doc

gates = tables.gates
BINARY_ORDER = "Latin1_General_100_BIN2"      # exact (case-sensitive) order, as MongoDB sorted strings
_ACTIVE = gates.c.is_active == true()


async def active_ids(db: SqlDb, limit: int) -> list[UUID]:
    """IDs of up to `limit` active gates (callers use limit=2 to tell "exactly one" from "several")."""
    async with connection(db) as conn:
        return list((await conn.execute(select(gates.c.id).where(_ACTIVE).order_by(gates.c.id).limit(limit)))
                    .scalars())


async def count_active(db: SqlDb, limit: int) -> int:
    """Number of active gates, counted up to `limit`."""
    first = select(gates.c.id).where(_ACTIVE).limit(limit).subquery()
    async with connection(db) as conn:
        return (await conn.execute(select(func.count()).select_from(first))).scalar_one()


async def find_active(db: SqlDb, gate_id: UUID | str) -> dict | None:
    """The gate if it exists and is active. A string ID must already be validated (see schemas.common)."""
    gate_id = gate_id if isinstance(gate_id, UUID) else ids.to_id(gate_id)
    async with connection(db) as conn:
        return as_doc((await conn.execute(select(gates).where(gates.c.id == gate_id, _ACTIVE))).first())


async def find_active_names(db: SqlDb, *, gate_id: UUID | None = None, limit: int = 1) -> list[dict]:
    """_id and name of active gates: the one with `gate_id`, or (without it) up to `limit` of them."""
    query = select(gates.c.id, gates.c.name).where(_ACTIVE)
    query = query.where(gates.c.id == gate_id) if gate_id is not None else query.order_by(gates.c.id).limit(limit)
    async with connection(db) as conn:
        return [as_doc(row) for row in await conn.execute(query)]


async def list_all(db: SqlDb, limit: int) -> list[dict]:
    """Every gate, active ones first, then by name (exact, case-sensitive order)."""
    query = select(gates).order_by(gates.c.is_active.desc(), gates.c.name.collate(BINARY_ORDER)).limit(limit)
    async with connection(db) as conn:
        return [as_doc(row) for row in await conn.execute(query)]


async def find_any_active(db: SqlDb) -> dict | None:
    async with connection(db) as conn:
        return as_doc((await conn.execute(select(gates).where(_ACTIVE).order_by(gates.c.id).limit(1))).first())
