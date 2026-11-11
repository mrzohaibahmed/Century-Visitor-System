"""
`harness.store`: direct access to the stored records for tests that inspect or prepare them.

MongoDB: the database itself. SQL Server: SqlStore below, which offers the same few collection calls the
tests use (find_one, find(...).sort().to_list() / async for, count_documents, insert_one, update_one /
update_many with $set) on the SQL tables, and returns records in the shape the repositories return them.
Filters: equality (None = no value), and $in / $ne / $gt / $gte / $lt / $lte; field names as in the
documents ("_id", "actor.username", "identity.number", and fields inside the audit's JSON such as
"metadata.permission"). Anything else raises NotImplementedError, so a test never silently checks less.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import Table, and_, func, or_, select, true, update
from sqlalchemy import insert as sql_insert

from app.repositories.mssql import audit_logs as sql_audit_logs
from app.repositories.mssql import notifications as sql_notifications
from app.repositories.mssql import settings as sql_settings
from app.repositories.mssql import tables
from app.repositories.mssql import visits as sql_visits
from app.repositories.mssql.connection import connection
from app.repositories.mssql.rows import as_doc, identity_columns, new_row
from app.repositories.mssql.visitors import visitor_doc
from app.repositories.mssql.watchlist import entry_doc as watchlist_doc


def _same(doc: dict) -> dict:
    return doc


@dataclass(frozen=True)
class _Spec:
    table: Table
    to_doc: Callable = as_doc                                   # row -> document (as the repositories return it)
    to_columns: Callable = _same                                # document -> columns, for insert_one
    fields: dict[str, str] = field(default_factory=dict)        # document field -> column
    values: dict[str, Callable] = field(default_factory=dict)   # document field -> how its values are stored
    json_fields: frozenset = frozenset()                        # JSON columns whose inner fields can be filtered
    assemble: Callable | None = None      # async (conn, rows) -> documents, for records with child tables


_IDENTITY = {"identity.type": "identity_type", "identity.number": "identity_number"}
SPECS = {
    "users": _Spec(tables.users),
    "sessions": _Spec(tables.sessions),
    "rate_limits": _Spec(tables.rate_limits, fields={"_id": "window_key"}),
    "gates": _Spec(tables.gates),
    "departments": _Spec(tables.departments),
    "hosts": _Spec(tables.hosts),
    "visitors": _Spec(tables.visitors, visitor_doc, identity_columns, _IDENTITY),
    "photos": _Spec(tables.photos),
    "watchlist": _Spec(tables.watchlist, watchlist_doc, identity_columns, _IDENTITY),
    "notifications": _Spec(tables.notifications, sql_notifications.notification_doc,
                           sql_notifications.notification_columns,
                           fields={f"email.{name}": f"email_{name}" for name in sql_notifications.EMAIL_FIELDS},
                           json_fields=frozenset({"data"})),
    "entry_denials": _Spec(tables.entry_denials),
    "visits": _Spec(tables.visits, fields={
        **{f"pass.{name}": f"pass_{name}" for name in ("token_hash", "issued_at", "expires_at", "issued_by",
                                                         "revoked_at", "revoked_by")},
        **{f"snapshot.{key}": column for key, column in sql_visits.SNAPSHOT.items()}},
        assemble=lambda conn, rows: sql_visits.assemble_visits(conn, rows, hide_pass_secrets=False)),
    "audit_logs": _Spec(tables.audit_logs, sql_audit_logs.entry_doc, sql_audit_logs.entry_columns, fields={
        "actor.user_id": "actor_user_id", "actor.username": "actor_username", "actor.role": "actor_role",
        "resource.type": "resource_type", "resource.id": "resource_id"},
        values={"resource.id": str},                            # stored as text (a GUID or a key)
        json_fields=frozenset({"metadata", "changes"})),
}


def _json_text(value):
    """How JSON_VALUE returns a scalar: text; true/false in lower case."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise NotImplementedError(f"harness.store: filtering a JSON field by {type(value).__name__}")
_COMPARISONS = {"$gt": "__gt__", "$gte": "__ge__", "$lt": "__lt__", "$lte": "__le__"}


async def _pause(conn, table: Table, which: str) -> str:
    """Switches off the table's foreign keys ("foreign_keys") or all its constraints ("all") for the rest of
    this transaction; returns what to switch back on. Only ever used on the throw-away test database."""
    if which == "all":
        await conn.exec_driver_sql(f"ALTER TABLE dbo.{table.name} NOCHECK CONSTRAINT ALL")
        return "ALL"
    if which != "foreign_keys":
        raise ValueError(f"pause_constraints: {which}")
    names = (await conn.exec_driver_sql(
        f"SELECT name FROM sys.foreign_keys WHERE parent_object_id = OBJECT_ID('dbo.{table.name}')")).scalars().all()
    if not names:
        return ""
    joined = ", ".join(f"[{name}]" for name in names)
    await conn.exec_driver_sql(f"ALTER TABLE dbo.{table.name} NOCHECK CONSTRAINT {joined}")
    return joined


class SqlStore:
    def __init__(self, db):
        self._db = db

    def __getitem__(self, name: str):
        return getattr(self, name)

    def __getattr__(self, name: str):
        if name == "settings":
            return SqlSettings(self._db)
        if name not in SPECS:
            raise NotImplementedError(f"harness.store has no SQL Server mapping for '{name}' yet")
        return SqlCollection(self._db, SPECS[name])


class SqlSettings:
    """harness.store.settings: the documents of repositories/mssql/settings.py, found by their key
    ({"_id": "email_smtp"} / {"_id": "gate_camera:<gate id>"}), or all of them with find({})."""

    def __init__(self, db):
        self._db = db

    @staticmethod
    def _key(query: dict) -> str:
        if set(query) != {"_id"}:
            raise NotImplementedError(f"harness.store.settings: query {query} (only by _id)")
        return query["_id"]

    async def find_one(self, query: dict) -> dict | None:
        return await sql_settings.get(self._db, self._key(query))

    def find(self, query: dict | None = None) -> "_Listed":
        if query:
            raise NotImplementedError("harness.store.settings.find: only find({})")
        return _Listed(self._all)

    async def _all(self) -> list[dict]:
        async with connection(self._db) as conn:
            gates = (await conn.execute(select(tables.gate_cameras.c.gate_id))).scalars().all()
        keys = [sql_settings.EMAIL_KEY, *(f"{sql_settings.CAMERA_PREFIX}{gate}" for gate in gates)]
        return await sql_settings.get_many(self._db, keys)

    async def update_one(self, query: dict, change: dict) -> None:
        if set(change) != {"$set"}:
            raise NotImplementedError(f"harness.store.settings: update {sorted(change)} (only $set)")
        await sql_settings.set_fields(self._db, self._key(query), change["$set"])


class _Listed:
    def __init__(self, load):
        self._load = load

    async def to_list(self, length: int | None = None) -> list[dict]:
        docs = await self._load()
        return docs[:length] if length else docs


class SqlCollection:
    def __init__(self, db, spec: _Spec):
        self._db, self._spec = db, spec

    def _column(self, name: str):
        head, _, rest = name.partition(".")
        if rest and head in self._spec.json_fields:
            # A field inside a JSON column (audit metadata / changes): compared as JSON_VALUE's text.
            path = "$." + ".".join(f'"{part}"' for part in rest.split("."))
            return func.JSON_VALUE(self._spec.table.c[head], path)
        column = self._spec.fields.get(name) or ("id" if name == "_id" else name)
        if column not in self._spec.table.c:
            raise NotImplementedError(f"{self._spec.table.name} has no column for field '{name}'")
        return self._spec.table.c[column]

    def _where(self, query: dict | None):
        clauses = []
        for name, condition in (query or {}).items():
            column = self._column(name)
            in_json = name.partition(".")[0] in self._spec.json_fields and "." in name
            stored = _json_text if in_json else self._spec.values.get(name, _same)
            if isinstance(condition, dict) and condition and all(k.startswith("$") for k in condition):
                for op, value in condition.items():
                    if op == "$in":
                        clauses.append(column.in_([stored(v) for v in value]))
                    elif op == "$ne":
                        clauses.append(column.is_not(None) if value is None
                                       else or_(column != stored(value), column.is_(None)))
                    elif op in _COMPARISONS:
                        clauses.append(getattr(column, _COMPARISONS[op])(stored(value)))
                    elif op == "$regex" and isinstance(value, str) and value.replace("_", "").isalnum():
                        clauses.append(column.contains(value, autoescape=True))     # a plain "contains" regex
                    elif op == "$regex":
                        raise NotImplementedError(f"harness.store: $regex {value!r} (only plain text)")
                    else:
                        raise NotImplementedError(f"harness.store: operator {op}")
            elif condition is None:
                clauses.append(column.is_(None))
            else:
                clauses.append(column == stored(condition))
        return and_(*clauses) if clauses else true()

    def _order(self):
        table = self._spec.table
        return table.c.id if "id" in table.c else list(table.primary_key.columns)[0]

    async def find_one(self, query: dict | None = None) -> dict | None:
        found = await self.find(query).to_list(1)
        return found[0] if found else None

    def find(self, query: dict | None = None) -> "SqlCursor":
        return SqlCursor(self, query)

    async def count_documents(self, query: dict | None = None) -> int:
        statement = select(func.count()).select_from(self._spec.table).where(self._where(query))
        async with connection(self._db) as conn:
            return (await conn.execute(statement)).scalar_one()

    async def insert_one(self, doc: dict, *, pause_constraints: str | None = None):
        """Inserts `doc` as the repositories would (doc["_id"] is set); returns .inserted_id like MongoDB.
        pause_constraints ("foreign_keys" or "all", see conftest.insert_seed): this one insert runs with the
        table's foreign keys (and CHECKs) switched off, in its own transaction; unique indexes still apply."""
        table = self._spec.table
        async with connection(self._db) as conn:
            paused = await _pause(conn, table, pause_constraints) if pause_constraints else ""
            if table is tables.visits:              # the visit with its children, as the repository writes it
                await sql_visits.insert(self._db, doc, session=conn)
            else:
                await conn.execute(sql_insert(table), new_row(table, doc, self._spec.to_columns(doc)))
            if paused:
                await conn.exec_driver_sql(f"ALTER TABLE dbo.{table.name} WITH NOCHECK CHECK CONSTRAINT {paused}")
        return SimpleNamespace(inserted_id=doc["_id"])

    async def insert_many(self, docs: list[dict], **options):
        for doc in docs:
            await self.insert_one(doc, **options)
        return SimpleNamespace(inserted_ids=[doc["_id"] for doc in docs])

    async def delete_many(self, query: dict | None = None):
        async with connection(self._db) as conn:
            result = await conn.execute(self._spec.table.delete().where(self._where(query)))
        return SimpleNamespace(deleted_count=result.rowcount)

    def _values(self, change: dict) -> dict:
        if set(change) != {"$set"}:
            raise NotImplementedError(f"harness.store: update {sorted(change)} (only $set)")
        return {self._column(name).name: value for name, value in change["$set"].items()}

    async def update_one(self, query: dict, change: dict) -> None:
        table = self._spec.table
        first = select(self._order()).where(self._where(query)).order_by(self._order()).limit(1).scalar_subquery()
        async with connection(self._db) as conn:
            await conn.execute(update(table).where(self._order() == first).values(**self._values(change)))

    async def update_many(self, query: dict, change: dict) -> None:
        async with connection(self._db) as conn:
            await conn.execute(update(self._spec.table).where(self._where(query)).values(**self._values(change)))


class SqlCursor:
    def __init__(self, collection: SqlCollection, query: dict | None):
        self._collection, self._query = collection, query
        self._sort: list = []

    def sort(self, name: str, direction: int = 1) -> "SqlCursor":
        column = self._collection._column(name)
        self._sort.append(column.desc() if direction < 0 else column.asc())
        return self

    async def to_list(self, length: int | None = None) -> list[dict]:
        c = self._collection
        # The default order (insertion) breaks ties, unless the sort already uses that column (SQL Server
        # refuses a column listed twice in ORDER BY).
        sorted_by = {getattr(term, "element", term).name for term in self._sort}
        tie_break = [] if c._order().name in sorted_by else [c._order()]
        statement = select(c._spec.table).where(c._where(self._query)).order_by(*self._sort, *tie_break)
        if length:
            statement = statement.limit(length)
        async with connection(c._db) as conn:
            rows = (await conn.execute(statement)).all()
            if c._spec.assemble is not None:
                return await c._spec.assemble(conn, rows)
        return [c._spec.to_doc(row) for row in rows]

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for doc in await self.to_list(None):
            yield doc
