"""Persistence for the ``fact_check`` job: load child claims, append verdict rows.

Functions take an injected async session so the job handler can be tested with
fakes. Each ``record_*`` call commits, so a finished child is durable even if a
later child fails.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import FACT_CHECK_VERDICTS, ChunkRun, Clause, FactCheck, ParentChunk
from .scope import Scope

#: Verdicts that set ``Clause.fact_check_passed``; every other verdict leaves it untouched.
PASSED_BY_VERDICT: dict[str, bool] = {"supported": True, "contradicted": False}


@dataclass(frozen=True)
class ChildClaim:
    """One active-run child clause plus the parent text and SFL/tokens the gate reads."""

    external_id: str
    text: str
    parent_text: str | None
    notebook_id: str | None
    parent_id: int | None
    sfl: dict[str, Any] | None
    tokens: list[dict[str, Any]] | None


class VerdictResult(Protocol):
    """The fields :func:`record_fact_check` reads from a checker result."""

    verdict: str
    confidence: float | None
    probabilities: dict[str, float] | None
    sift_steps: dict[str, Any] | None
    citations: list[dict[str, Any]] | None
    model: str | None


async def load_children(
    session: AsyncSession,
    notebook_id: str | None = None,
    parent_id: int | None = None,
    *,
    scope: Scope | None = None,
) -> list[ChildClaim]:
    """Child clauses in scope, in id order.

    ``notebook_id`` / ``parent_id`` are the TUI's notebook scope; ``scope``
    narrows by documents, runs or an explicit chunk selection instead (see
    :class:`~notebooklm._app.scope.Scope`).
    """
    effective = scope or Scope(notebook_id=notebook_id, parent_id=parent_id)
    if scope is not None and (notebook_id is not None or parent_id is not None):
        effective = replace(
            scope,
            notebook_id=notebook_id or scope.notebook_id,
            parent_id=parent_id if parent_id is not None else scope.parent_id,
        )
    stmt = (
        select(Clause, ParentChunk.text, ChunkRun.notebook_id)
        .join(ChunkRun, Clause.run_id == ChunkRun.id)
        .outerjoin(ParentChunk, Clause.parent_id == ParentChunk.id)
        .order_by(Clause.id)
    )
    stmt = effective.apply(stmt)
    result = await session.execute(stmt)
    return [
        ChildClaim(
            external_id=clause.external_id,
            text=clause.text,
            parent_text=parent_text,
            notebook_id=nb_id,
            parent_id=clause.parent_id,
            sfl=clause.sfl,
            tokens=clause.tokens if isinstance(clause.tokens, list) else None,
        )
        for clause, parent_text, nb_id in result.all()
    ]


async def record_fact_check(
    session: AsyncSession,
    clause_external_id: str,
    result: VerdictResult,
    *,
    job_id: str | None,
    trace_id: str | None,
    latency_ms: int | None,
) -> None:
    """Append one ``fact_checks`` row; set ``fact_check_passed`` for supported/contradicted only."""
    if result.verdict not in FACT_CHECK_VERDICTS:
        raise ValueError(f"Unknown fact-check verdict {result.verdict!r}")
    session.add(
        FactCheck(
            clause_external_id=clause_external_id,
            job_id=job_id,
            verdict=result.verdict,
            confidence=result.confidence,
            probabilities=result.probabilities,
            sift_steps=result.sift_steps,
            citations=result.citations,
            trace_id=trace_id,
            model=result.model,
            latency_ms=latency_ms,
        )
    )
    if result.verdict in PASSED_BY_VERDICT:
        await session.execute(
            update(Clause)
            .where(Clause.external_id == clause_external_id)
            .values(fact_check_passed=PASSED_BY_VERDICT[result.verdict])
        )
    await session.commit()


async def record_not_checkworthy(
    session: AsyncSession,
    clause_external_id: str,
    *,
    job_id: str | None,
    trace_id: str | None,
) -> None:
    """Append a ``not_checkworthy`` row. No checker ran, so there is no model or latency."""
    session.add(
        FactCheck(
            clause_external_id=clause_external_id,
            job_id=job_id,
            verdict="not_checkworthy",
            trace_id=trace_id,
        )
    )
    await session.commit()
