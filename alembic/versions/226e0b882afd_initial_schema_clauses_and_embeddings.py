"""Initial schema: clauses and embeddings

Revision ID: 226e0b882afd
Revises:
Create Date: 2026-09-17 04:39:56.326893

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '226e0b882afd'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # Create clauses table
    op.create_table(
        'clauses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('external_id', sa.String(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('document_id', sa.String(), nullable=False),
        sa.Column('sentence_index', sa.Integer(), nullable=True),
        sa.Column('root_index', sa.Integer(), nullable=True),
        sa.Column('tokens', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('groups', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_clauses_document_id'), 'clauses', ['document_id'], unique=False)
    op.create_index(op.f('ix_clauses_external_id'), 'clauses', ['external_id'], unique=True)

    op.execute("CREATE INDEX idx_clauses_tsv ON clauses USING gin(to_tsvector('english', text));")

    # Create embeddings table
    op.create_table(
        'embeddings',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('clause_id', sa.String(), nullable=False),
        sa.Column('embedding', Vector(dim=768), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['clause_id'], ['clauses.external_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.execute("CREATE INDEX idx_embeddings_hnsw ON embeddings USING hnsw (embedding vector_l2_ops) WITH (m = 16, ef_construction = 64);")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('embeddings')
    op.drop_table('clauses')
