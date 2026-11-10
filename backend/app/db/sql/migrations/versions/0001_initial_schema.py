"""Initial schema: the port of MongoDB schema v10 (app/db/sql/0001_initial_schema.sql, reviewed as SQL).

Revision ID: 0001
Revises:
Created: 2026-11-10
"""
from alembic import op

from app.db.sql.batches import read_batches

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for batch in read_batches("0001_initial_schema.sql"):
        # Sent as written (no bind-parameter parsing: comments contain ":" and the SQL has no parameters).
        connection.exec_driver_sql(batch)


def downgrade() -> None:
    # Forward-only: restore a backup instead of running a downgrade on production data.
    raise NotImplementedError("Downgrades are not supported; restore the database backup.")
