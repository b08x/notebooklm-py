"""Add removal_log and archived_notebooks

Revision ID: e7a4c1f9b3d2
Revises: 2abace98a31c
Create Date: 2026-09-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e7a4c1f9b3d2"
down_revision: str | Sequence[str] | None = "2abace98a31c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "removal_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notebook_id", sa.String(), nullable=False),
        sa.Column("notebook_title", sa.String(), nullable=False),
        sa.Column("item_id", sa.String(), nullable=False),
        sa.Column("item_title", sa.String(), nullable=False),
        sa.Column("item_type", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("archive_path", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_removal_log_notebook_id", "removal_log", ["notebook_id"])

    op.create_table(
        "archived_notebooks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("notebook_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("archive_path", sa.String(), nullable=False),
        sa.Column("document_ids", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("remote_deleted", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_archived_notebooks_notebook_id", "archived_notebooks", ["notebook_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_archived_notebooks_notebook_id", table_name="archived_notebooks")
    op.drop_table("archived_notebooks")
    op.drop_index("ix_removal_log_notebook_id", table_name="removal_log")
    op.drop_table("removal_log")
