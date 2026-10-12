"""Corpus notebook titles

A ``corpus_notebooks`` row per notebook ever seen in the corpus, holding its
last known title so the Corpus Explorer can show titles without a signed-in
NotebookLM client. Backfilled from the two tables that already record titles:
``archived_notebooks`` and ``removal_log``.

Revision ID: c4d9e2a6b7f1
Revises: f2c1a7d4e9b0
Create Date: 2026-10-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d9e2a6b7f1"
down_revision: str | Sequence[str] | None = "f2c1a7d4e9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "corpus_notebooks",
        sa.Column("notebook_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("notebook_id"),
    )
    op.execute(
        "INSERT INTO corpus_notebooks (notebook_id, title, updated_at) "
        "SELECT notebook_id, min(title), now() FROM ("
        " SELECT notebook_id, title FROM archived_notebooks"
        " UNION ALL"
        " SELECT notebook_id, notebook_title AS title FROM removal_log"
        ") s GROUP BY notebook_id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("corpus_notebooks")
