"""
SQL Server connections: SQLAlchemy Core (no ORM) over Microsoft "ODBC Driver 18 for SQL Server".

- async_engine(): the API's connection pool (aioodbc), for the repositories.
- sync_engine():  plain pyodbc, for Alembic migrations and the admin commands (python -m app.db.sql).

The ODBC connection string is built here from the CG_MSSQL_* settings. The password only ever goes
into that string; it is never logged, and connection errors are reported by type, never with the
string (see describe_error).
"""
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import Settings

APP_NAME = "century-gate-vms-api"


def _braced(value: str) -> str:
    """An ODBC attribute value in braces (so ; and = inside it are safe); } is doubled."""
    return "{" + value.replace("}", "}}") + "}"


def odbc_connection_string(settings: Settings, *, database: str | None = None) -> str:
    """The ODBC connection string. `database` overrides CG_MSSQL_DATABASE (e.g. "master" to create it)."""
    parts = {
        "Driver": _braced(settings.mssql_driver),
        "Server": _braced(settings.mssql_server),
        "Database": _braced(database or settings.mssql_database),
        "Encrypt": "yes",                                     # always: ODBC Driver 18's default, made explicit
        "TrustServerCertificate": "yes" if settings.mssql_trust_server_certificate else "no",
        "Connection Timeout": str(settings.mssql_timeout_seconds),
        "APP": _braced(APP_NAME),
    }
    if settings.mssql_username:
        parts["UID"] = _braced(settings.mssql_username)
        parts["PWD"] = _braced(settings.mssql_password.get_secret_value())
    else:
        parts["Trusted_Connection"] = "yes"                    # Windows authentication
    return ";".join(f"{k}={v}" for k, v in parts.items())


def _url(dialect: str, settings: Settings, database: str | None) -> URL:
    return URL.create(dialect, query={"odbc_connect": odbc_connection_string(settings, database=database)})


def async_engine(settings: Settings) -> AsyncEngine:
    """The API's pool. pool_pre_ping: a connection broken by a SQL Server restart is replaced, not used."""
    return create_async_engine(_url("mssql+aioodbc", settings, None), pool_pre_ping=True, pool_size=5,
                               max_overflow=10, pool_recycle=1800, hide_parameters=True)


def sync_engine(settings: Settings, *, database: str | None = None, autocommit: bool = False) -> Engine:
    """For migrations and admin commands. autocommit: needed for CREATE/ALTER DATABASE."""
    options = {"isolation_level": "AUTOCOMMIT"} if autocommit else {}
    return create_engine(_url("mssql+pyodbc", settings, database), hide_parameters=True, **options)


def describe_error(error: BaseException) -> str:
    """A connection error for logs and the console: the driver's SQLSTATE and type, never the connection
    string or password (pyodbc messages can quote the server, never the password, but stay careful)."""
    orig = getattr(error, "orig", error)
    state = orig.args[0] if getattr(orig, "args", None) and isinstance(orig.args[0], str) else None
    return f"{type(orig).__name__}{f' (SQLSTATE {state})' if state else ''}"
