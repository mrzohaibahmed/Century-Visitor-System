"""Alembic environment: migrations run with the API's own settings (CG_MSSQL_*), never a URL in a file.

Run through `python -m app.db.sql migrate` (which also refuses the legacy database), not `alembic`.
"""
from alembic import context

from app.core.config import get_settings
from app.db.sql.engine import sync_engine


def run_migrations_online() -> None:
    engine = context.config.attributes.get("engine") or sync_engine(get_settings())
    with engine.connect() as connection:
        # SQL Server runs DDL inside transactions: a migration that fails leaves nothing half-created.
        context.configure(connection=connection, transaction_per_migration=True, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not used: run `python -m app.db.sql migrate`.")
run_migrations_online()
