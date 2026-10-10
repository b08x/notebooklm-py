"""Parent/child chunks, chunk_runs provenance, fact_checks history, topics

Truncates the legacy flat clauses (test database; the archive is re-ingested).

Revision ID: f2c1a7d4e9b0
Revises: e7a4c1f9b3d2
Create Date: 2026-10-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f2c1a7d4e9b0"
down_revision: str | Sequence[str] | None = "e7a4c1f9b3d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VERDICTS = (
    "supported",
    "contradicted",
    "unverifiable",
    "skipped_no_framework",
    "not_checkworthy",
)


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("TRUNCATE clauses, embeddings CASCADE")

    op.create_table(
        "chunk_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("notebook_id", sa.String(), nullable=True),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("chunker_version", sa.String(), nullable=False),
        sa.Column("source_hash", sa.String(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("n_parents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_children", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mean_len", sa.Float(), nullable=False, server_default="0"),
        sa.Column("p95_len", sa.Float(), nullable=False, server_default="0"),
        sa.Column("entity_vetoes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chunk_runs_document_id", "chunk_runs", ["document_id"])
    op.create_index("ix_chunk_runs_notebook_id", "chunk_runs", ["notebook_id"])

    op.create_table(
        "parent_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("chunk_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_parent_chunks_run_id", "parent_chunks", ["run_id"])
    op.create_index("ix_parent_chunks_document_id", "parent_chunks", ["document_id"])

    op.create_table(
        "topic_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("n_docs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("n_topics", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("topic_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("topic_number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_topics_run_id", "topics", ["run_id"])

    op.add_column(
        "clauses",
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("chunk_runs.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column(
        "clauses",
        sa.Column(
            "parent_id",
            sa.Integer(),
            sa.ForeignKey("parent_chunks.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.add_column("clauses", sa.Column("sfl", postgresql.JSONB(), nullable=True))
    op.add_column(
        "clauses",
        sa.Column(
            "topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="SET NULL"), nullable=True
        ),
    )
    op.create_index("ix_clauses_run_id", "clauses", ["run_id"])
    op.create_index("ix_clauses_parent_id", "clauses", ["parent_id"])
    op.create_index("ix_clauses_topic_id", "clauses", ["topic_id"])

    verdict = postgresql.ENUM(*VERDICTS, name="fact_check_verdict")
    verdict.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "fact_checks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "clause_external_id",
            sa.String(),
            sa.ForeignKey("clauses.external_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("job_id", sa.String(), nullable=True),
        sa.Column(
            "verdict",
            postgresql.ENUM(*VERDICTS, name="fact_check_verdict", create_type=False),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("probabilities", postgresql.JSONB(), nullable=True),
        sa.Column("sift_steps", postgresql.JSONB(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=True),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_checks_clause_external_id", "fact_checks", ["clause_external_id"])
    op.create_index("ix_fact_checks_job_id", "fact_checks", ["job_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("fact_checks")
    postgresql.ENUM(name="fact_check_verdict").drop(op.get_bind(), checkfirst=True)
    for ix in ("ix_clauses_topic_id", "ix_clauses_parent_id", "ix_clauses_run_id"):
        op.drop_index(ix, table_name="clauses")
    for col in ("topic_id", "sfl", "parent_id", "run_id"):
        op.drop_column("clauses", col)
    op.drop_table("topics")
    op.drop_table("topic_runs")
    op.drop_table("parent_chunks")
    op.drop_table("chunk_runs")
