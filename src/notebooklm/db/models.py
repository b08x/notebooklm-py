import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    literal_column,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class LocalAsset(Base):
    __tablename__ = "local_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notebook_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    asset_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String, nullable=False)  # 'source' or 'artifact'
    local_path: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Clause(Base):
    __tablename__ = "clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sentence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    groups: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    fact_check_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "idx_clauses_tsv",
            func.to_tsvector(literal_column("'english'"), text),
            postgresql_using="gin",
        ),
    )


class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clause_id: Mapped[str] = mapped_column(
        String, ForeignKey("clauses.external_id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        Index(
            "idx_embeddings_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_l2_ops"},
        ),
    )


class RemovalLog(Base):
    """One row per curated removal, notebook delete, or archive.

    Local Postgres data is never purged; this table is the audit trail that
    records what was removed, when, and why.
    """

    __tablename__ = "removal_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notebook_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    notebook_title: Mapped[str] = mapped_column(String, nullable=False)
    item_id: Mapped[str] = mapped_column(String, nullable=False)
    item_title: Mapped[str] = mapped_column(String, nullable=False)
    #: One of ``source`` | ``artifact`` | ``note`` | ``mind_map`` | ``notebook``.
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    #: One of ``remove`` | ``delete_notebook`` | ``archive``.
    action: Mapped[str] = mapped_column(String, nullable=False)
    #: One of ``REMOVAL_REASONS`` (see ``notebooklm._app.curation``).
    reason: Mapped[str] = mapped_column(String, nullable=False)
    #: Set only for ``action == "archive"``.
    archive_path: Mapped[str | None] = mapped_column(String, nullable=True)


class ArchivedNotebook(Base):
    """Remote notebook gone, local rows kept and still findable.

    Deleting or archiving a notebook never deletes local clauses, embeddings,
    or ``local_assets`` rows; this record is what keeps them findable by
    notebook after the remote notebook no longer exists.
    """

    __tablename__ = "archived_notebooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    notebook_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    archive_path: Mapped[str] = mapped_column(String, nullable=False)
    #: Every document id (sources, artifacts, notes) whose local clauses and
    #: embeddings survive the remote delete.
    document_ids: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str] = mapped_column(String, nullable=False)
    remote_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
