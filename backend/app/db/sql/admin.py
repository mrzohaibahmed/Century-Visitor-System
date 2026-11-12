"""
SQL Server administration for the VMS database (CG_MSSQL_* settings, backend/.env); run through app/cli.py:

    python -m app.cli create-database   creates CG_MSSQL_DATABASE if it does not exist (collation,
                                        read-committed snapshot); never changes an existing database
    python -m app.cli migrate           applies the Alembic migrations (idempotent, forward-only)
    python -m app.cli check             connection, schema revision, isolation settings (exit 1 if not ready)
    python -m app.cli backup [--to DIR] a full copy-only backup file (.bak), verified after writing

Each returns a report without the password or the connection string.
"""
import ntpath
from datetime import datetime

from alembic import command
from sqlalchemy import text

from app.core.config import Settings
from app.db.sql.engine import sync_engine
from app.db.sql.revision import alembic_config, current_revision, head_revision

COLLATION = "Latin1_General_100_CI_AS_SC"    # case-insensitive, accent-sensitive


def create_database(settings: Settings) -> dict:
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


def migrate(settings: Settings) -> dict:
    engine = sync_engine(settings)
    try:
        command.upgrade(alembic_config(engine), "head")
        with engine.connect() as conn:
            current = current_revision(conn)
    finally:
        engine.dispose()
    return {"database": settings.mssql_database, "revision": current, "head": head_revision()}


def check(settings: Settings) -> dict:
    engine = sync_engine(settings)
    try:
        with engine.connect() as conn:
            current = current_revision(conn)
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


def backup(settings: Settings, folder: str | None = None) -> dict:
    """A full backup of the application database to <folder>\\<database>-<local time>.bak: COPY_ONLY (it does
    not disturb any other backup plan on the instance), with page checksums, then read back once with
    RESTORE VERIFYONLY. The SQL Server SERVICE writes the file, so `folder` is a path on the database server
    that its service account may write to; default: the instance's own backup folder. The photo folder
    (CG_PHOTO_DIR) is not in the database: back it up at the same time (README)."""
    name = settings.mssql_database                   # validated: letters, digits, _ (safe unquoted)
    engine = sync_engine(settings, database="master", autocommit=True)   # BACKUP cannot run in a transaction
    try:
        with engine.connect() as conn:
            if not folder:
                folder = conn.execute(text(
                    "SELECT CAST(SERVERPROPERTY('InstanceDefaultBackupPath') AS nvarchar(4000))")).scalar()
            path = ntpath.join(folder, f"{name}-{datetime.now():%Y%m%d-%H%M%S}.bak")
            cursor = conn.connection.cursor()
            try:
                # Each statement reports progress as messages: read them all, or it may end before it is done.
                cursor.execute(f"BACKUP DATABASE [{name}] TO DISK = ? WITH COPY_ONLY, CHECKSUM, INIT, "
                               "NAME = N'Century Gate VMS'", path)
                while cursor.nextset():
                    pass
                cursor.execute("RESTORE VERIFYONLY FROM DISK = ? WITH CHECKSUM", path)
                while cursor.nextset():
                    pass
            finally:
                cursor.close()
            size = conn.execute(text(
                "SELECT TOP 1 backup_size FROM msdb.dbo.backupset WHERE database_name = :name "
                "AND type = 'D' ORDER BY backup_finish_date DESC"), {"name": name}).scalar()
    finally:
        engine.dispose()
    return {"database": name, "file": path, "bytes": int(size) if size is not None else None, "verified": True}
