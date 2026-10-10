"""Read-only queries over the chunked corpus for the Ingest and Fact-check modes.

All functions take an open ``AsyncSession`` and return plain dicts so the TUI
renderers stay free of ORM objects (and of lazy-load IO on the render thread).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ChunkRun, Clause, FactCheck, ParentChunk, Topic


def _run_dict(run: ChunkRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "document_id": run.document_id,
        "strategy": run.strategy,
        "chunker_version": run.chunker_version,
        "params": run.params,
        "trace_id": run.trace_id,
        "n_parents": run.n_parents,
        "n_children": run.n_children,
        "mean_len": run.mean_len,
        "p95_len": run.p95_len,
        "entity_vetoes": run.entity_vetoes,
        "is_active": run.is_active,
        "source_hash": run.source_hash,
        "created_at": run.created_at,
    }


async def active_runs(session: AsyncSession, notebook_id: str) -> list[dict[str, Any]]:
    """The active run of every document ingested for ``notebook_id``."""
    stmt = (
        select(ChunkRun)
        .where(ChunkRun.notebook_id == notebook_id, ChunkRun.is_active.is_(True))
        .order_by(ChunkRun.document_id)
    )
    return [_run_dict(r) for r in (await session.execute(stmt)).scalars()]


async def document_runs(session: AsyncSession, document_id: str) -> list[dict[str, Any]]:
    """Every run of one document, newest first (for ``x`` compare)."""
    stmt = select(ChunkRun).where(ChunkRun.document_id == document_id).order_by(ChunkRun.id.desc())
    return [_run_dict(r) for r in (await session.execute(stmt)).scalars()]


async def parents(session: AsyncSession, run_id: int) -> list[dict[str, Any]]:
    """Parents of a run in order, each with its child count."""
    counts = (
        select(Clause.parent_id, func.count().label("n"))
        .where(Clause.run_id == run_id)
        .group_by(Clause.parent_id)
        .subquery()
    )
    stmt = (
        select(ParentChunk, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.parent_id == ParentChunk.id)
        .where(ParentChunk.run_id == run_id)
        .order_by(ParentChunk.index)
    )
    return [
        {"id": p.id, "index": p.index, "text": p.text, "n_children": int(n)}
        for p, n in (await session.execute(stmt)).all()
    ]


async def children(session: AsyncSession, parent_id: int) -> list[dict[str, Any]]:
    """Children of one parent with spaCy features, SFL output and topic label."""
    stmt = (
        select(Clause, Topic.label)
        .outerjoin(Topic, Topic.id == Clause.topic_id)
        .where(Clause.parent_id == parent_id)
        .order_by(Clause.sentence_index)
    )
    return [
        {
            "external_id": c.external_id,
            "text": c.text,
            "tokens": c.tokens or [],
            "groups": c.groups or {},
            "root_index": c.root_index,
            "sfl": c.sfl,
            "topic": label,
            "fact_check_passed": c.fact_check_passed,
        }
        for c, label in (await session.execute(stmt)).all()
    ]


async def claims(
    session: AsyncSession, notebook_id: str, verdict: str | None = None
) -> list[dict[str, Any]]:
    """Newest fact-check per child of the notebook's active runs.

    ``verdict`` filters on the newest verdict (``None`` = all checked children).
    """
    latest = (
        select(FactCheck)
        .distinct(FactCheck.clause_external_id)
        .order_by(FactCheck.clause_external_id, FactCheck.id.desc())
        .subquery()
    )
    stmt = (
        select(Clause, ParentChunk.text.label("parent_text"), latest)
        .join(latest, latest.c.clause_external_id == Clause.external_id)
        .join(ChunkRun, ChunkRun.id == Clause.run_id)
        .outerjoin(ParentChunk, ParentChunk.id == Clause.parent_id)
        .where(ChunkRun.notebook_id == notebook_id, ChunkRun.is_active.is_(True))
        .order_by(Clause.document_id, Clause.sentence_index)
    )
    if verdict is not None:
        stmt = stmt.where(latest.c.verdict == verdict)
    out = []
    for row in (await session.execute(stmt)).all():
        fc = row._mapping
        clause = fc[Clause]
        out.append(
            {
                "external_id": clause.external_id,
                "text": clause.text,
                "sfl": clause.sfl,
                "parent_text": fc["parent_text"],
                "verdict": fc["verdict"],
                "confidence": fc["confidence"],
                "probabilities": fc["probabilities"],
                "sift_steps": fc["sift_steps"],
                "citations": fc["citations"],
                "trace_id": fc["trace_id"],
                "model": fc["model"],
                "latency_ms": fc["latency_ms"],
            }
        )
    return out
