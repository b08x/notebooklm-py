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
