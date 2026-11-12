"""
SQL Server access for visits and their passes (queries only; rules live in services).
Visits come back as documents:

    visits row          -> the visit; snap_* columns -> "snapshot"; pass_* columns -> "pass"
    visit_belongings    -> "belongings" (in the order entered)
    visit_personal_material + visit_material_items -> "personal_material" (or None)
    visit_replaced_passes -> "pass"["revoked_token_hashes"] (badges replaced by a reissue)

Lists and responses never carry the pass's secrets: hide_pass_secrets leaves only {"expires_at"}.
The children of a page of visits are read with one query per child table.
"""
from datetime import date, datetime
from uuid import UUID

from sqlalchemy import and_, delete, func, or_, select, text, true, update
from sqlalchemy import insert as sql_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.sql.database import SqlDb
from app.repositories import ids, tables
from app.repositories.connection import connection
from app.repositories.errors import duplicates_as_domain_error
from app.repositories.rows import checked
from app.repositories.visit_filter import VisitFilter

visits = tables.visits
belongings_table = tables.visit_belongings
slips = tables.visit_personal_material
slip_items = tables.visit_material_items
replaced = tables.visit_replaced_passes
counters = tables.visit_number_counters

SNAPSHOT = {"visitor_name": "snap_visitor_name", "host_name": "snap_host_name",
            "department_name": "snap_department_name", "gate_name": "snap_gate_name",
            "checked_in_by_name": "snap_checked_in_by_name", "checked_out_by_name": "snap_checked_out_by_name",
            "checkout_gate_name": "snap_checkout_gate_name"}
PLAIN = ("visit_number", "visitor_id", "host_id", "host_unlisted", "department_id", "gate_id", "checkout_gate_id",
         "reason_code", "reason_note", "vehicle_registration", "status", "check_in_at", "check_out_at",
         "checked_in_by", "checked_out_by", "checkout_method", "photo_id", "created_at", "updated_at")
SLIP_FIELDS = ("contact_name", "remarks", "authorised_by", "issued_by", "gate_officer")
NEWEST_FIRST = (visits.c.check_in_at.desc(), visits.c.id.desc())
_CHECKED_IN = visits.c.status == "CHECKED_IN"


# ------------------------------------------------------------------------------------------ rows <-> visits
def _pass_columns(visit_pass: dict | None) -> dict:
    visit_pass = visit_pass or {}
    sealed = visit_pass.get("qr_sealed") or {}
    return {"pass_token_hash": visit_pass.get("token_hash"), "pass_issued_at": visit_pass.get("issued_at"),
            "pass_expires_at": visit_pass.get("expires_at"), "pass_issued_by": visit_pass.get("issued_by"),
            "pass_revoked_at": visit_pass.get("revoked_at"), "pass_revoked_by": visit_pass.get("revoked_by"),
            "pass_qr_version": sealed.get("v"), "pass_qr_kid": sealed.get("kid"),
            "pass_qr_nonce": sealed.get("nonce"), "pass_qr_ct": sealed.get("ct")}


def _visit_columns(visit: dict) -> dict:
    row = {key: visit.get(key) for key in PLAIN} | {"id": visit["_id"]}
    snapshot = visit.get("snapshot") or {}
    row |= {column: snapshot.get(key) for key, column in SNAPSHOT.items()}
    return checked(visits, row | _pass_columns(visit.get("pass")))


def _pass_doc(m: dict, revoked_hashes: list[str], hide_pass_secrets: bool) -> dict | None:
    if m["pass_token_hash"] is None:
        return None
    if hide_pass_secrets:
        return {"expires_at": m["pass_expires_at"]}
    visit_pass = {"token_hash": m["pass_token_hash"], "issued_at": m["pass_issued_at"],
                  "expires_at": m["pass_expires_at"], "issued_by": m["pass_issued_by"],
                  "revoked_at": m["pass_revoked_at"], "revoked_by": m["pass_revoked_by"],
                  "revoked_token_hashes": revoked_hashes}
    if m["pass_qr_ct"] is not None:
        visit_pass["qr_sealed"] = {"v": m["pass_qr_version"], "kid": m["pass_qr_kid"],
                                   "nonce": bytes(m["pass_qr_nonce"]), "ct": bytes(m["pass_qr_ct"])}
    return visit_pass


def _slip_doc(slip, items: list) -> dict:
    return {"contact_name": slip.contact_name,
            "date": slip.material_date.isoformat() if slip.material_date else None,
            "items": [{"description": i.description, "qty_in": i.qty_in, "qty_out": i.qty_out} for i in items],
            "remarks": slip.remarks, "authorised_by": slip.authorised_by, "issued_by": slip.issued_by,
            "gate_officer": slip.gate_officer}


async def assemble_visits(conn: AsyncConnection, rows: list, *, hide_pass_secrets: bool) -> list[dict]:
    """Visit documents for these rows, children included (one query per child table)."""
    if not rows:
        return []
    ids = [row.id for row in rows]
    things: dict = {visit_id: [] for visit_id in ids}
    for row in await conn.execute(select(belongings_table).where(belongings_table.c.visit_id.in_(ids))
                                  .order_by(belongings_table.c.visit_id, belongings_table.c.position)):
        things[row.visit_id].append(row.description)
    slip_rows = {row.visit_id: row for row in await conn.execute(select(slips).where(slips.c.visit_id.in_(ids)))}
    items: dict = {visit_id: [] for visit_id in slip_rows}
    if slip_rows:
        for row in await conn.execute(select(slip_items).where(slip_items.c.visit_id.in_(list(slip_rows)))
                                      .order_by(slip_items.c.visit_id, slip_items.c.position)):
            items[row.visit_id].append(row)
    revoked: dict = {visit_id: [] for visit_id in ids}
    if not hide_pass_secrets:
        for row in await conn.execute(select(replaced).where(replaced.c.visit_id.in_(ids))
                                      .order_by(replaced.c.visit_id, replaced.c.replaced_at)):
            revoked[row.visit_id].append(row.token_hash)
    docs = []
    for row in rows:
        m = dict(row._mapping)
        doc = {"_id": m["id"], **{key: m[key] for key in PLAIN}}
        doc["snapshot"] = {key: m[column] for key, column in SNAPSHOT.items()}
        doc["belongings"] = things[row.id]
        doc["personal_material"] = _slip_doc(slip_rows[row.id], items[row.id]) if row.id in slip_rows else None
        doc["pass"] = _pass_doc(m, revoked[row.id], hide_pass_secrets)
        docs.append(doc)
    return docs


async def _find(conn: AsyncConnection, where, *, hide_pass_secrets: bool) -> dict | None:
    rows = (await conn.execute(select(visits).where(where).limit(1))).all()
    found = await assemble_visits(conn, rows, hide_pass_secrets=hide_pass_secrets)
    return found[0] if found else None


async def _write_belongings(conn: AsyncConnection, visit_id: UUID, items: list[str]) -> None:
    if items:
        await conn.execute(sql_insert(belongings_table), [
            {"visit_id": visit_id, "position": n, "description": description} for n, description in enumerate(items)])


async def _write_slip(conn: AsyncConnection, visit_id: UUID, material: dict | None) -> None:
    if material is None:
        return
    day = material.get("date")
    await conn.execute(sql_insert(slips), {
        "visit_id": visit_id, "material_date": date.fromisoformat(day) if day else None,
        **{name: material.get(name) or "" for name in SLIP_FIELDS}})
    if material.get("items"):
        await conn.execute(sql_insert(slip_items), [
            {"visit_id": visit_id, "position": n, "description": item["description"],
             "qty_in": item.get("qty_in"), "qty_out": item.get("qty_out")}
            for n, item in enumerate(material["items"])])


# ------------------------------------------------------------------------------------------ filters
def filter_query(f: VisitFilter, *, visit_number: str | None = None, visitor_ids: list[UUID] | None = None):
    """The database filter for `f` (a SQL condition on dbo.visits), with the free-text search `f.q` already
    resolved by the caller into a `visit_number` or a list of `visitor_ids` (which replaces `f.visitor_id`).
    Starts from check_in_at (indexed) when a range is given."""
    clauses = []
    if f.status:
        clauses.append(visits.c.status == f.status)
    if f.start:
        clauses.append(visits.c.check_in_at >= f.start)
    if f.end:
        clauses.append(visits.c.check_in_at < f.end)
    for column, value in ((visits.c.host_id, f.host_id), (visits.c.department_id, f.department_id),
                          (visits.c.gate_id, f.gate_id)):
        if value:
            clauses.append(column == value)
    if visitor_ids is not None and visit_number is None:
        clauses.append(visits.c.visitor_id.in_(visitor_ids))
    elif f.visitor_id:
        clauses.append(visits.c.visitor_id == f.visitor_id)
    if f.guard_id:
        clauses.append(or_(visits.c.checked_in_by == f.guard_id, visits.c.checked_out_by == f.guard_id))
    if f.reason_code:
        clauses.append(visits.c.reason_code == f.reason_code)
    if visit_number is not None:
        clauses.append(visits.c.visit_number == visit_number)
    return and_(true(), *clauses)


# ------------------------------------------------------------------------------------------ reads
async def find_by_id(db: SqlDb, visit_id: UUID, *, hide_pass_secrets: bool = False,
                     session: AsyncConnection | None = None) -> dict | None:
    """The visit; with hide_pass_secrets, without the pass token, revocation and print data."""
    async with connection(db, session) as conn:
        return await _find(conn, visits.c.id == visit_id, hide_pass_secrets=hide_pass_secrets)


async def find_by_number(db: SqlDb, visit_number: str) -> dict | None:
    async with connection(db) as conn:
        return await _find(conn, visits.c.visit_number == visit_number, hide_pass_secrets=False)


async def find_active_for_visitor(db: SqlDb, visitor_id: UUID) -> dict | None:
    """The visitor's visit that is CHECKED_IN right now (at most one, enforced by a unique index)."""
    async with connection(db) as conn:
        return await _find(conn, and_(visits.c.visitor_id == visitor_id, _CHECKED_IN), hide_pass_secrets=False)


async def is_photo_of_active_visit(db: SqlDb, photo_id: UUID) -> bool:
    query = select(visits.c.id).where(visits.c.photo_id == photo_id, _CHECKED_IN).limit(1)
    async with connection(db) as conn:
        return (await conn.execute(query)).first() is not None


async def list_overstayed(db: SqlDb, now: datetime, limit: int) -> list[dict]:
    """CHECKED_IN visits whose badge expired at or before `now` (full documents)."""
    query = select(visits).where(_CHECKED_IN, visits.c.pass_expires_at <= now).order_by(visits.c.id).limit(limit)
    async with connection(db) as conn:
        return await assemble_visits(conn, (await conn.execute(query)).all(), hide_pass_secrets=False)


async def list_active(db: SqlDb, limit: int) -> list[dict]:
    """CHECKED_IN visits, latest check-in first, without pass secrets."""
    query = select(visits).where(_CHECKED_IN).order_by(*NEWEST_FIRST).limit(limit)
    async with connection(db) as conn:
        return await assemble_visits(conn, (await conn.execute(query)).all(), hide_pass_secrets=True)


async def count_active(db: SqlDb) -> int:
    async with connection(db) as conn:
        return (await conn.execute(select(func.count()).select_from(visits).where(_CHECKED_IN))).scalar_one()


async def list_page(db: SqlDb, query, *, after: tuple[datetime, UUID] | None, limit: int) -> list[dict]:
    """Visits matching `query` (from filter_query), newest check-in first, without pass secrets.
    `after`: the (check_in_at, ID) of the last row already shown."""
    statement = select(visits).where(query)
    if after:
        last_at, last_id = after
        statement = statement.where(or_(visits.c.check_in_at < last_at,
                                        and_(visits.c.check_in_at == last_at, visits.c.id < last_id)))
    async with connection(db) as conn:
        rows = (await conn.execute(statement.order_by(*NEWEST_FIRST).limit(limit))).all()
        return await assemble_visits(conn, rows, hide_pass_secrets=True)


# ------------------------------------------------------------------------------------------ writes
async def next_daily_number(db: SqlDb, day: date, session: AsyncConnection) -> int:
    """1, 2, 3, ... per (local) day; atomic across gates and part of the caller's transaction (MERGE with
    HOLDLOCK: two check-ins that both find no counter for the day cannot both create it)."""
    result = await session.execute(text(
        "MERGE dbo.visit_number_counters WITH (HOLDLOCK) AS counter "
        "USING (SELECT CAST(:day AS DATE) AS day) AS wanted ON counter.day = wanted.day "
        "WHEN MATCHED THEN UPDATE SET seq = counter.seq + 1 "
        "WHEN NOT MATCHED THEN INSERT (day, seq) VALUES (wanted.day, 1) "
        "OUTPUT inserted.seq;"), {"day": day})
    return result.scalar_one()


async def insert(db: SqlDb, visit: dict, session: AsyncConnection | None = None) -> UUID:
    """Raises DuplicateKey if the visitor already has a CHECKED_IN visit (or the number is taken).
    Sets visit["_id"] (a new ID, or the one the document already has); the belongings and the
    Personal Material slip are written with it."""
    visit["_id"] = visit.get("_id") or ids.new_id()
    row = _visit_columns(visit)
    with duplicates_as_domain_error():
        async with connection(db, session) as conn:
            await conn.execute(sql_insert(visits), row)
            await _write_belongings(conn, visit["_id"], visit.get("belongings") or [])
            await _write_slip(conn, visit["_id"], visit.get("personal_material"))
    return visit["_id"]


async def check_out_if_active(db: SqlDb, visit_id: UUID, *, now: datetime, user_id: UUID, user_name: str,
                              gate_id: UUID | None, gate_name: str | None, method: str,
                              session: AsyncConnection | None = None) -> dict | None:
    """CHECKED_IN -> CHECKED_OUT in one conditional update (only one request can win).
    Returns the updated visit, or None if it was not checked in."""
    async with connection(db, session) as conn:
        result = await conn.execute(update(visits).where(visits.c.id == visit_id, _CHECKED_IN).values(
            status="CHECKED_OUT", check_out_at=now, checked_out_by=user_id, checkout_gate_id=gate_id,
            checkout_method=method, snap_checked_out_by_name=user_name, snap_checkout_gate_name=gate_name,
            updated_at=now))
        if result.rowcount == 0:
            return None
        return await _find(conn, visits.c.id == visit_id, hide_pass_secrets=False)


async def update_belongings_if_active(db: SqlDb, visit_id: UUID, *, belongings: list[str],
                                      vehicle_registration: str | None, set_personal_material: bool,
                                      personal_material: dict | None, now: datetime,
                                      session: AsyncConnection | None = None) -> dict | None:
    """Replaces belongings and vehicle (and, with set_personal_material, the Personal Material slip) on a
    CHECKED_IN visit. Returns the updated visit without pass secrets, or None if it was not checked in."""
    async with connection(db, session) as conn:
        result = await conn.execute(update(visits).where(visits.c.id == visit_id, _CHECKED_IN)
                                    .values(vehicle_registration=vehicle_registration, updated_at=now))
        if result.rowcount == 0:
            return None
        await conn.execute(delete(belongings_table).where(belongings_table.c.visit_id == visit_id))
        await _write_belongings(conn, visit_id, belongings)
        if set_personal_material:
            await conn.execute(delete(slip_items).where(slip_items.c.visit_id == visit_id))
            await conn.execute(delete(slips).where(slips.c.visit_id == visit_id))
            await _write_slip(conn, visit_id, personal_material)
        return await _find(conn, visits.c.id == visit_id, hide_pass_secrets=True)


# --- passes (the pass_* columns and visit_replaced_passes) ---

async def set_pass_if_active(db: SqlDb, visit_id: UUID, new_pass: dict, now: datetime,
                             session: AsyncConnection | None = None) -> None:
    """Replaces the whole pass (token, expiry, revoked tokens, print data) on a CHECKED_IN visit."""
    async with connection(db, session) as conn:
        result = await conn.execute(update(visits).where(visits.c.id == visit_id, _CHECKED_IN)
                                    .values(**_pass_columns(new_pass), updated_at=now))
        if result.rowcount == 0:
            return
        known = set((await conn.execute(select(replaced.c.token_hash).where(replaced.c.visit_id == visit_id)))
                    .scalars())
        new = [h for h in dict.fromkeys(new_pass.get("revoked_token_hashes") or []) if h not in known]
        if new:
            await conn.execute(sql_insert(replaced), [{"token_hash": h, "visit_id": visit_id, "replaced_at": now}
                                                      for h in new])


async def revoke_pass(db: SqlDb, visit_id: UUID, *, user_id: UUID, now: datetime,
                      session: AsyncConnection | None = None) -> None:
    async with connection(db, session) as conn:
        await conn.execute(update(visits).where(visits.c.id == visit_id)
                           .values(pass_revoked_at=now, pass_revoked_by=user_id, updated_at=now))


async def find_by_pass_token(db: SqlDb, token_hash: str) -> dict | None:
    """The visit whose current pass has this token hash (full document, including the pass)."""
    async with connection(db) as conn:
        return await _find(conn, visits.c.pass_token_hash == token_hash, hide_pass_secrets=False)


async def find_by_replaced_pass_token(db: SqlDb, token_hash: str) -> dict | None:
    """_id and visit_number of the visit whose pass was reissued, replacing this token."""
    query = (select(visits.c.id, visits.c.visit_number).join(replaced, replaced.c.visit_id == visits.c.id)
             .where(replaced.c.token_hash == token_hash))
    async with connection(db) as conn:
        row = (await conn.execute(query)).first()
    return {"_id": row.id, "visit_number": row.visit_number} if row else None
