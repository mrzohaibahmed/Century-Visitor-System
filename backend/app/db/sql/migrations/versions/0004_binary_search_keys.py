"""Name search keys compare exactly: binary collation (app/db/sql/0004_binary_search_keys.sql).

Revision ID: 0004
Revises: 0003
Created: 2026-11-11
"""
from alembic import op

from app.db.sql.batches import read_batches

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for batch in read_batches("0004_binary_search_keys.sql"):
        connection.exec_driver_sql(batch)      # as written, no bind-parameter parsing


def downgrade() -> None:
    # Forward-only: restore a backup instead of running a downgrade on production data.
    raise NotImplementedError("Downgrades are not supported; restore the database backup.")
