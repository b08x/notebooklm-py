"""Add fact_check_passed to clauses

Revision ID: d3f8a1c9b2e4
Revises: acc6b9b32ee1
Create Date: 2026-09-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3f8a1c9b2e4"
down_revision: str | Sequence[str] | None = "acc6b9b32ee1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("clauses", sa.Column("fact_check_passed", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("clauses", "fact_check_passed")
