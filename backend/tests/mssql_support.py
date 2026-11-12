"""
SQL Server test database: created and migrated ONCE per test session (cgvms_test_<random>), emptied before
each test that uses it, dropped at the end. (A database per test would cost seconds per
test on SQL Server.) The instance: CG_TEST_MSSQL_SERVER, default this PC's .\\SQLEXPRESS, Windows login.
"""
import os
import uuid

from sqlalchemy import text

from app.core.config import Settings, mssql_server_is_local
from app.db.sql.admin import create_database, migrate
from app.db.sql.engine import sync_engine

TEST_MSSQL_SERVER = os.environ.get("CG_TEST_MSSQL_SERVER", ".\\SQLEXPRESS")
TEST_DATABASE_PREFIX = "cgvms_test_"

# Every table, children before parents (foreign keys); the visitor -> photo -> visit cycle is cut first.
# tests/test_mssql_foundation.py checks that no table is missing here.
EMPTY_ALL_TABLES = """
UPDATE dbo.visitors SET current_photo_id = NULL;
UPDATE dbo.photos SET visit_id = NULL;
DELETE FROM dbo.visit_material_items;
DELETE FROM dbo.visit_personal_material;
DELETE FROM dbo.visit_belongings;
DELETE FROM dbo.visit_replaced_passes;
DELETE FROM dbo.notifications;
DELETE FROM dbo.visits;
DELETE FROM dbo.photos;
DELETE FROM dbo.visitors;
DELETE FROM dbo.watchlist;
DELETE FROM dbo.entry_denials;
DELETE FROM dbo.audit_logs;
DELETE FROM dbo.gate_cameras;
DELETE FROM dbo.email_settings;
DELETE FROM dbo.sessions;
DELETE FROM dbo.rate_limits;
DELETE FROM dbo.visit_number_counters;
DELETE FROM dbo.hosts;
DELETE FROM dbo.departments;
DELETE FROM dbo.gates;
UPDATE dbo.users SET created_by = NULL;
DELETE FROM dbo.users;
"""


def new_test_database_name() -> str:
    return f"{TEST_DATABASE_PREFIX}{uuid.uuid4().hex[:10]}"


def sql_settings_overrides(database: str) -> dict:
    return {"mssql_server": TEST_MSSQL_SERVER, "mssql_database": database,
            # A local instance has a self-signed certificate; a server on the network must be trusted properly.
            "mssql_trust_server_certificate": mssql_server_is_local(TEST_MSSQL_SERVER), "mssql_timeout_seconds": 5}


def create_test_database(settings: Settings) -> None:
    """Creates and migrates the test database (raises sqlalchemy DBAPIError if SQL Server is not reachable)."""
    _refuse_unless_test_database(settings)
    _drop_stale_test_databases(settings)
    create_database(settings)
    migrate(settings)


def drop_test_database(settings: Settings) -> None:
    _refuse_unless_test_database(settings)
    engine = sync_engine(settings, database="master", autocommit=True)
    try:
        with engine.connect() as conn:
            _drop(conn, settings.mssql_database)
    finally:
        engine.dispose()


def _refuse_unless_test_database(settings: Settings) -> None:
    if not settings.mssql_database.startswith(TEST_DATABASE_PREFIX):
        raise RuntimeError(f"Refusing to touch a database that is not a test database: {settings.mssql_database}")


def _drop(conn, name: str) -> None:
    if not name.startswith(TEST_DATABASE_PREFIX):            # never anything else, whatever the caller passes
        raise RuntimeError(f"Refusing to drop {name}")
    if conn.execute(text("SELECT DB_ID(:name)"), {"name": name}).scalar() is not None:
        conn.exec_driver_sql(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
        conn.exec_driver_sql(f"DROP DATABASE [{name}]")


def _drop_stale_test_databases(settings: Settings) -> None:
    """Test databases left behind by an interrupted run (older than a day) are dropped."""
    engine = sync_engine(settings, database="master", autocommit=True)
    try:
        with engine.connect() as conn:
            stale = conn.execute(text(
                "SELECT name FROM sys.databases WHERE name LIKE :prefix ESCAPE '\\' "
                "AND create_date < DATEADD(day, -1, SYSDATETIME())"),
                {"prefix": TEST_DATABASE_PREFIX.replace("_", "\\_") + "%"}).scalars().all()
            for name in stale:
                _drop(conn, name)
    finally:
        engine.dispose()


async def empty_all_tables(database) -> None:
    """Every row of every table goes (the schema and its migration record stay)."""
    async with database.engine.begin() as conn:
        await conn.exec_driver_sql(EMPTY_ALL_TABLES)


def empty_all_tables_sync(settings: Settings) -> None:
    """The same, for synchronous fixtures."""
    _refuse_unless_test_database(settings)
    engine = sync_engine(settings)
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql(EMPTY_ALL_TABLES)
    finally:
        engine.dispose()
