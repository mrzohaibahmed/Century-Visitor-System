"""
SQL Server administration for the VMS database (CG_MSSQL_* settings, backend/.env).

    python -m app.db.sql create-database   creates CG_MSSQL_DATABASE if it does not exist (collation,
                                           read-committed snapshot); never changes an existing database
    python -m app.db.sql migrate           applies the Alembic migrations (idempotent, forward-only)
    python -m app.db.sql check             connection, schema revision, isolation settings (exit 1 if not ready)

Each prints JSON without the password or the connection string.
"""
import json
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.config import get_settings
from app.db.sql.engine import describe_error, sync_engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
COLLATION = "Latin1_General_100_CI_AS_SC"    # case-insensitive, accent-sensitive (= MongoDB strength 2)


def alembic_config(engine=None) -> Config:
    config = Config()
    # Only script_location: the revisions are found in its versions/ folder. (version_locations would be
    # split on spaces, and this project lives in "D:\Visitor System".)
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def create_database() -> dict:
    settings = get_settings()
    name = settings.mssql_database                   # validated: letters, digits, _ (safe unquoted)
    engine = sync_engine(settings, database="master", autocommit=True)
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT DB_ID(:name)"), {"name": name}).scalar() is not None
            if not exists:
                conn.exec_driver_sql(f"CREATE DATABASE [{name}] COLLATE {COLLATION}")
                conn.exec_driver_sql(f"ALTER DATABASE [{name}] SET READ_COMMITTED_SNAPSHOT ON")
                conn.exec_driver_sql(f"ALTER DATABASE [{name}] SET ALLOW_SNAPSHOT_ISOLATION ON")
    finally:
        engine.dispose()
    return {"database": name, "created": not exists}


def migrate() -> dict:
    settings = get_settings()
    engine = sync_engine(settings)
    try:
        command.upgrade(alembic_config(engine), "head")
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
    return {"database": settings.mssql_database, "revision": current, "head": head_revision()}


def check() -> dict:
    settings = get_settings()
    engine = sync_engine(settings)
    try:
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
            row = conn.execute(text(
                "SELECT CAST(SERVERPROPERTY('ProductVersion') AS nvarchar(32)), "
                "CAST(SERVERPROPERTY('Edition') AS nvarchar(64)), collation_name, is_read_committed_snapshot_on "
                "FROM sys.databases WHERE name = DB_NAME()")).one()
    finally:
        engine.dispose()
    head = head_revision()
    report = {"database": settings.mssql_database, "server_version": row[0], "edition": row[1],
              "collation": row[2], "read_committed_snapshot": bool(row[3]), "revision": current,
              "expected_revision": head}
    report["ready"] = head is not None and current == head and row[2] == COLLATION and bool(row[3])
    return report


COMMANDS = {"create-database": create_database, "migrate": migrate, "check": check}


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    try:
        report = COMMANDS[argv[0]]()
    except DBAPIError as e:
        print(json.dumps({"error": describe_error(e)}))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report.get("ready", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
