import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
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


class ChunkRun(Base):
    """One chunking pass over one document: strategy, parameters, provenance.

    Several runs of the same document may coexist (``x`` compare in the Ingest
    mode); exactly one per document has ``is_active`` set.
    """

    __tablename__ = "chunk_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    notebook_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    #: Registry name: ``recursive`` | ``cluster_semantic`` | ``dynamic_window``.
    strategy: Mapped[str] = mapped_column(String, nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    chunker_version: Mapped[str] = mapped_column(String, nullable=False)
    #: sha256 hex of the source text, so runs over identical input are comparable.
    source_hash: Mapped[str] = mapped_column(String, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    n_parents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_children: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    mean_len: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    p95_len: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    entity_vetoes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ParentChunk(Base):
    """A large context unit (paragraph/section block); children point at it."""

    __tablename__ = "parent_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chunk_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)


class TopicRun(Base):
    """One BERTopic fit over the corpus's active-run children."""

    __tablename__ = "topic_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    n_docs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    n_topics: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("topic_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: BERTopic's own topic number (``-1`` is the outlier bucket).
    topic_number: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String, nullable=False)
    keywords: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Clause(Base):
    """A child chunk: the unit that is embedded, tagged, and fact-checked.

    ``external_id`` is ``{document_id}:{run_id}:{index}``.
    """

    __tablename__ = "clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String, unique=True, index=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    document_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("chunk_runs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("parent_chunks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    sentence_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    root_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Per-token spaCy features: ``[{text, lemma, pos, tag, dep, head, morph}, ...]``.
    tokens: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: Noun-chunk and clause groups: ``{"noun_chunks": [...], "clauses": [...]}``.
    groups: Mapped[list[Any] | dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: SFL pass output: ``{mood, modality, tenor, pass1}``; NULL until ``sfl_tag`` runs.
    sfl: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    topic_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("topics.id", ondelete="SET NULL"), nullable=True, index=True
    )
    #: Mirrors the newest ``supported``/``contradicted`` verdict; NULL otherwise.
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


#: Values of ``fact_checks.verdict``.
FACT_CHECK_VERDICTS = (
    "supported",
    "contradicted",
    "unverifiable",
    "skipped_no_framework",
    "not_checkworthy",
)


class FactCheck(Base):
    """One fact-check attempt on one child. Re-runs append; nothing is overwritten."""

    __tablename__ = "fact_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    clause_external_id: Mapped[str] = mapped_column(
        String, ForeignKey("clauses.external_id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: The job id that produced this row (``nblm:job:<id>``).
    job_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    verdict: Mapped[str] = mapped_column(
        Enum(*FACT_CHECK_VERDICTS, name="fact_check_verdict"), nullable=False
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    probabilities: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: ``{stop, investigate_source, find_coverage, trace_claim}``.
    sift_steps: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    #: ``[{url, title, quote}, ...]``.
    citations: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CorpusNotebook(Base):
    """Last known title of one notebook present in the corpus.

    Written at ingest and refreshed by every successful live
    ``notebooks.list()``, so the UI can show titles even while the server has
    no signed-in NotebookLM client.
    """

    __tablename__ = "corpus_notebooks"

    notebook_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RemovalLog(Base):
    """One row per curated removal, notebook delete, or archive.

    Local Postgres data is purged only by the Corpus Explorer's confirmed
    delete (``action="delete_local"``, ``item_type`` clause/parent/document/run);
    this table is the audit trail that records what was removed, when, and why.
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
    #: One of ``source`` | ``artifact`` | ``note`` | ``mind_map`` | ``notebook``,
    #: or (local deletes) ``clause`` | ``parent`` | ``document`` | ``run``.
    item_type: Mapped[str] = mapped_column(String, nullable=False)
    #: One of ``remove`` | ``delete_notebook`` | ``archive`` | ``delete_local``.
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
