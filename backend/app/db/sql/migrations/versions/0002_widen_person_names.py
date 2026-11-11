"""Person names up to 100 characters (app/db/sql/0002_widen_person_names.sql).

Revision ID: 0002
Revises: 0001
Created: 2026-11-10
"""
from alembic import op

from app.db.sql.batches import read_batches

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    for batch in read_batches("0002_widen_person_names.sql"):
        connection.exec_driver_sql(batch)      # as written, no bind-parameter parsing


def downgrade() -> None:
    # Forward-only: restore a backup instead of running a downgrade on production data.
    raise NotImplementedError("Downgrades are not supported; restore the database backup.")
