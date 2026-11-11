"""The schema revision: the migrations this code expects (head) and the one a database is at (current)."""
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def alembic_config(engine: Engine | None = None) -> Config:
    config = Config()
    # Only script_location: the revisions are found in its versions/ folder. (version_locations would be
    # split on spaces, and this project lives in "D:\Visitor System".)
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if engine is not None:
        config.attributes["engine"] = engine
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(connection: Connection) -> str | None:
    """The revision recorded in this database (None: never migrated). Takes a synchronous connection."""
    return MigrationContext.configure(connection).get_current_revision()


def schema_status(current: str | None) -> str:
    """For /health/ready: ok, missing (never migrated) or outdated (an older or unknown revision)."""
    if current is None:
        return "missing"
    return "ok" if current == head_revision() else "outdated"
