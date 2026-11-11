"""
SQL Server foundation (step 4a of the move from MongoDB), against a real SQL Server test database
(skipped when none is reachable): record IDs, UTC times, duplicate-key translation, transactions,
health, the table definitions, and the loader that picks each repository's backend.
"""
import re
import sys
import types
import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pyodbc
import pytest
from sqlalchemy import bindparam, func, insert, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError

from app.db.errors import DuplicateKey
from app.db.sql import transactions as sql_transactions
from app.db.sql.engine import sync_engine
from app.db.sql.errors import is_deadlock, is_duplicate_key, native_errors
from app.repositories import _backend
from app.repositories.mssql import ids, tables
from app.repositories.mssql.connection import connection
from app.repositories.mssql.errors import DATABASE_ERRORS, duplicates_as_domain_error
from tests.mssql_support import EMPTY_ALL_TABLES

pytestmark = pytest.mark.anyio
NOW = datetime(2026, 11, 10, 9, 30, 15, 123456, tzinfo=UTC)


def gate_row(name: str) -> dict:
    return {"id": ids.new_id(), "name": name, "is_active": True, "created_at": NOW, "updated_at": NOW}


async def count(db, table) -> int:
    async with connection(db) as conn:
        return (await conn.execute(select(func.count()).select_from(table))).scalar_one()


# ------------------------------------------------------------------------------------------ table definitions
def _type_text(column_type, dialect) -> str:
    """The SQL type without its collation (compared separately). `dialect`: the connected engine's, which
    knows the server version (a bare mssql dialect assumes an old server: NTEXT, DATETIME for DATE)."""
    return re.sub(r" COLLATE \S+", "", column_type.compile(dialect=dialect)).upper()


def _binary_collation(column_type) -> bool:
    return "BIN2" in (getattr(column_type, "collation", None) or "")


def test_table_definitions_match_the_migrated_database(mssql_test_settings):
    engine = sync_engine(mssql_test_settings)
    try:
        inspector = sa_inspect(engine)
        with engine.connect() as conn:            # reflection does not report DATETIME2's precision; this does
            precision = {(t, c): p for t, c, p in conn.execute(text(
                "SELECT TABLE_NAME, COLUMN_NAME, DATETIME_PRECISION FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = 'dbo' AND DATA_TYPE = 'datetime2'"))}
        dialect = engine.dialect                  # initialised with the server version by the connection above
        assert dialect.server_version_info >= (15,)
        in_database = set(inspector.get_table_names(schema="dbo")) - {"alembic_version"}
        assert in_database == {t.name for t in tables.metadata.sorted_tables}
        problems = []
        for table in tables.metadata.sorted_tables:
            reflected = {c["name"]: c for c in inspector.get_columns(table.name, schema="dbo")}
            if set(reflected) != set(table.c.keys()):
                problems.append(f"{table.name}: columns {sorted(set(reflected) ^ set(table.c.keys()))}")
                continue
            for column in table.columns:
                found = reflected[column.name]
                if found["nullable"] != column.nullable:
                    problems.append(f"{table.name}.{column.name}: nullable {found['nullable']} != {column.nullable}")
                in_db, in_code = _type_text(found["type"], dialect), _type_text(column.type, dialect)
                if in_db == "DATETIME2":
                    in_db = f"DATETIME2({precision[(table.name, column.name)]})"
                if in_db != in_code:
                    problems.append(f"{table.name}.{column.name}: {in_db} != {in_code}")
                if _binary_collation(found["type"]) != _binary_collation(column.type):
                    problems.append(f"{table.name}.{column.name}: binary collation differs")
            primary_key = inspector.get_pk_constraint(table.name, schema="dbo")["constrained_columns"]
            if set(primary_key) != {c.name for c in table.primary_key.columns}:
                problems.append(f"{table.name}: primary key {primary_key}")
        assert problems == []
    finally:
        engine.dispose()


def test_emptying_the_test_database_covers_every_table():
    missing = [t.name for t in tables.metadata.sorted_tables if f"dbo.{t.name};" not in EMPTY_ALL_TABLES
               and f"dbo.{t.name} SET" not in EMPTY_ALL_TABLES]
    assert missing == []


# ------------------------------------------------------------------------------------------ record IDs
async def test_new_ids_sort_in_creation_order_in_sql_server(sql_database):
    made = [ids.new_id() for _ in range(500)]
    assert len(set(made)) == 500
    assert all(u.version == 8 and u.variant == uuid.RFC_4122 for u in made)
    async with sql_database.engine.begin() as conn:
        await conn.exec_driver_sql("CREATE TABLE #ids (n INT NOT NULL, id UNIQUEIDENTIFIER NOT NULL)")
        insert_ids = text("INSERT INTO #ids (n, id) VALUES (:n, :id)").bindparams(
            bindparam("id", type_=UNIQUEIDENTIFIER(as_uuid=True)))
        await conn.execute(insert_ids, [{"n": n, "id": made_id} for n, made_id in enumerate(made)])
        order = (await conn.execute(text("SELECT n FROM #ids ORDER BY id"))).scalars().all()
    assert order == list(range(500))          # SQL Server's GUID order is the order they were made in


def test_ids_have_one_text_form():
    made = ids.new_id()
    assert ids.parse_id(str(made)) == made and ids.parse_id(str(made).upper()) == made
    assert ids.parse_id(made) is made and ids.parse_id(None) is None and ids.is_id(made)
    for wrong in ["{" + str(made) + "}", made.hex, f"urn:uuid:{made}", "", "x" * 36, 12345, str(made) + "0"]:
        assert ids.parse_id(wrong) is None, wrong
        with pytest.raises(ValueError):
            ids.to_id(wrong)
    assert ids.to_id(str(made)) == made and not ids.is_id(str(made))


# ------------------------------------------------------------------------------------------ UTC times
async def test_times_round_trip_as_utc_cut_to_milliseconds_like_mongodb(sql_database):
    db = sql_database.db
    karachi = NOW.astimezone(ZoneInfo("Asia/Karachi"))                  # any aware time is stored as UTC
    async with connection(db) as conn:
        await conn.execute(insert(tables.rate_limits), {"window_key": "k", "count": 1, "expires_at": karachi})
    rate_limits = tables.rate_limits
    async with connection(db) as conn:
        stored = (await conn.execute(select(rate_limits.c.expires_at))).scalar_one()
        assert stored == NOW.replace(microsecond=123000) and stored.tzinfo is UTC
        # Both sides are cut to milliseconds, as MongoDB does: 15.123 vs 15.123999 compare as equal.
        later_same_ms = NOW.replace(microsecond=123999)
        before = select(func.count()).select_from(rate_limits).where(rate_limits.c.expires_at < later_same_ms)
        at_or_after = select(func.count()).select_from(rate_limits).where(rate_limits.c.expires_at >= later_same_ms)
        assert (await conn.execute(before)).scalar_one() == 0
        assert (await conn.execute(at_or_after)).scalar_one() == 1
    with pytest.raises(StatementError) as refused:
        async with connection(db) as conn:
            await conn.execute(insert(tables.rate_limits),
                               {"window_key": "naive", "count": 1, "expires_at": datetime(2026, 11, 10, 9, 30)})
    assert isinstance(refused.value.orig, ValueError)                  # a naive time is never guessed


# ------------------------------------------------------------------------------------------ errors
async def test_duplicates_become_duplicate_key_without_quoting_the_value(sql_database):
    db = sql_database.db
    async with connection(db) as conn:
        await conn.execute(insert(tables.gates), gate_row("North (547)"))
    with pytest.raises(DuplicateKey) as duplicate:
        with duplicates_as_domain_error():
            async with connection(db) as conn:
                await conn.execute(insert(tables.gates), gate_row("NORTH (547)"))   # unique ignoring case
    assert "NORTH" not in str(duplicate.value) and "547" not in str(duplicate.value)
    cause = duplicate.value.__cause__
    assert isinstance(cause, IntegrityError) and is_duplicate_key(cause)
    codes = native_errors(cause)                   # 2601, plus 3621 "The statement has been terminated."
    assert 2601 in codes and 547 not in codes      # the "(547)" inside the quoted value is not an error number
    assert await count(db, tables.gates) == 1


async def test_other_integrity_errors_stay_errors(sql_database):
    db = sql_database.db
    session_row = {"id": ids.new_id(), "token_hash": "a" * 64, "csrf_token_hash": "b" * 64,
                   "user_id": ids.new_id(), "created_at": NOW, "last_seen_at": NOW, "expires_at": NOW}
    with pytest.raises(IntegrityError) as broken:
        with duplicates_as_domain_error():
            async with connection(db) as conn:
                await conn.execute(insert(tables.sessions), session_row)           # no such user
    assert not isinstance(broken.value, DuplicateKey) and 547 in native_errors(broken.value)
    assert isinstance(broken.value, DATABASE_ERRORS)


def test_deadlocks_are_recognised():
    deadlock = OperationalError("UPDATE ...", None, pyodbc.Error(
        "40001", "[40001] [Microsoft][ODBC Driver 18 for SQL Server][SQL Server]Transaction (Process ID 61) was "
                 "deadlocked on lock resources with another process and has been chosen as the deadlock victim. "
                 "Rerun the transaction. (1205) (SQLExecDirectW)"))
    lost = OperationalError("SELECT 1", None, pyodbc.Error("08S01", "[08S01] Communication link failure (0) "
                                                                     "(SQLExecDirectW)"))
    assert is_deadlock(deadlock) and native_errors(deadlock) == {1205}
    assert not is_deadlock(lost)


# ------------------------------------------------------------------------------------------ transactions
async def test_a_transaction_commits_or_leaves_nothing(sql_database):
    db = sql_database.db

    async def add_gate(s):
        async with connection(db, s) as conn:                          # joins the caller's transaction
            await conn.execute(insert(tables.gates), gate_row("Main"))
        return "done"

    assert await sql_transactions.run_in_transaction(db, add_gate) == "done"
    assert await count(db, tables.gates) == 1

    async def add_then_fail(s):
        async with connection(db, s) as conn:
            await conn.execute(insert(tables.gates), gate_row("Second"))
        raise RuntimeError("a later step failed")

    with pytest.raises(RuntimeError):
        await sql_transactions.run_in_transaction(db, add_then_fail)
    assert await count(db, tables.gates) == 1                          # "Second" was rolled back


async def test_a_deadlock_victim_is_retried_and_other_errors_are_not(sql_database, monkeypatch):
    db = sql_database.db
    calls = []
    monkeypatch.setattr(sql_transactions.asyncio, "sleep", lambda _s: _no_wait())

    async def first_attempt_deadlocks(s):
        calls.append(len(calls) + 1)
        async with connection(db, s) as conn:
            await conn.execute(insert(tables.gates), gate_row(f"Attempt {len(calls)}"))
        if len(calls) == 1:
            raise OperationalError("INSERT ...", None, pyodbc.Error("40001", "deadlock victim (1205) (SQLExecute)"))
        return len(calls)

    assert await sql_transactions.run_in_transaction(db, first_attempt_deadlocks) == 2
    async with connection(db) as conn:
        names = (await conn.execute(select(tables.gates.c.name))).scalars().all()
    assert names == ["Attempt 2"]                                       # the first attempt left nothing

    attempts = []

    async def link_lost(s):
        attempts.append(1)
        raise OperationalError("SELECT 1", None, pyodbc.Error("08S01", "Communication link failure (0) (SQLExecute)"))

    with pytest.raises(OperationalError):
        await sql_transactions.run_in_transaction(db, link_lost)
    assert attempts == [1]


async def _no_wait():
    return None


# ------------------------------------------------------------------------------------------ health
async def test_the_sql_server_database_reports_its_health(sql_database):
    await sql_database.ping()
    assert await sql_database.transactions_available() is True
    assert await sql_database.schema_status() == "ok"


# ------------------------------------------------------------------------------------------ backend loader
def _fake_module(name: str, source: str) -> types.ModuleType:
    module = types.ModuleType(name)
    exec(source, module.__dict__)                  # noqa: S102 - fixed test source
    return module


def test_the_loader_takes_each_function_from_the_configured_backend(monkeypatch):
    mongo = _fake_module("app.repositories.mongo.example", (
        "LIMIT = 5\n"
        "class Shape:\n    pass\n"
        "async def find(db, x):\n    'Finds x.'\n    return 'mongo'\n"
        "def build(x):\n    return 'mongo'\n"))
    sql = _fake_module("app.repositories.mssql.example", "async def find(db, x):\n    return 'mssql'\n")
    monkeypatch.setitem(sys.modules, "app.repositories.mongo.example", mongo)
    monkeypatch.setitem(sys.modules, "app.repositories.mssql.example", sql)

    monkeypatch.setattr(_backend, "BACKEND", "mongo")
    assert _backend.load("app.repositories.example") == {"LIMIT": 5, "Shape": mongo.Shape, "find": mongo.find,
                                                         "build": mongo.build}

    monkeypatch.setattr(_backend, "BACKEND", "mssql")
    loaded = _backend.load("app.repositories.example")
    assert loaded["find"] is sql.find                                  # written for SQL Server: used
    assert loaded["LIMIT"] == 5 and loaded["Shape"] is mongo.Shape     # constants and classes: shared until then
    with pytest.raises(_backend.NotPortedYet, match=r"repositories\.example\.build has no SQL Server version"):
        loaded["build"]("x")                                           # not written yet: a clear error, not Mongo
    assert loaded["build"].__name__ == "build"


def test_an_area_without_any_sql_server_module_still_loads(monkeypatch):
    mongo = _fake_module("app.repositories.mongo.later", "async def find(db):\n    'Finds.'\n    return 1\n")
    monkeypatch.setitem(sys.modules, "app.repositories.mongo.later", mongo)
    monkeypatch.setattr(_backend, "BACKEND", "mssql")
    loaded = _backend.load("app.repositories.later")
    assert loaded["find"].__doc__ == "Finds."
    with pytest.raises(_backend.NotPortedYet):
        loaded["find"](None)
