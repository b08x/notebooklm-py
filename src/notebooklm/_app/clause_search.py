"""Semantic search over a notebook's ingested clauses, answered by an LLM.

Embeds a query with the same local embedder ``IngestionService`` uses, finds the
nearest ingested clauses for a notebook via pgvector, and synthesizes an answer
from just those clauses through the configured chat LLM (OpenRouter by default —
see :func:`notebooklm._app.assessment.setup_dspy_router`).

This is a separate concern from NotebookLM's own chat/citations
(``client.chat.ask``, exposed as the ``chat_ask`` MCP tool): it searches this
project's own local Postgres/pgvector ingestion store (regular sources ingested
via "Ingest Sources", plus any audio-overview transcript ingested via "Assess
Audio Overview"), not NotebookLM's server-side retrieval.

This module is transport-neutral — no ``click`` / ``rich`` / ``tui`` imports
(enforced by ``tests/_guardrails/test_app_boundary.py``), and is allowed to
depend on ``notebooklm._preprocessing`` (see that guardrail's docstring).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import dspy
from sqlalchemy import select

from .._preprocessing.embeddings import EmbeddingAdapter, OllamaEmbeddingAdapter
from ..db.models import Clause, Embedding
from .assessment import setup_dspy_router

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ..client import NotebookLMClient

logger = logging.getLogger(__name__)


class ClauseSearchAnswerSignature(dspy.Signature):
    """Answer the question using only the given context clauses. Say so plainly if the context is insufficient."""

    question = dspy.InputField(desc="The user's question.")
    context = dspy.InputField(desc="Retrieved clauses, most relevant first.")
    answer = dspy.OutputField(desc="A concise answer grounded only in the given context.")


@dataclass
class MatchedClause:
    """One nearest-neighbor clause match."""

    clause_id: str
    document_id: str
    text: str
    #: pgvector L2 distance to the query embedding — lower is a closer match.
    #: ``None`` for keyword-only matches that never went through the index.
    distance: float | None = None


@dataclass
class ClauseSearchResult:
    answer: str
    matched_clauses: list[MatchedClause] = field(default_factory=list)


async def _notebook_document_ids(client: NotebookLMClient, notebook_id: str) -> list[str]:
    """Every ``Clause.document_id`` ingested clauses could be keyed under for this notebook.

    Regular sources are ingested keyed by source id (``IngestionService.ingest_source``);
    an audio overview's transcript is ingested keyed by its artifact id
    (``_app.assessment.run_full_assessment``). Both are notebook-scoped listings, so
    their union is every document id this notebook's clauses could live under.
    """
    sources = await client.sources.list(notebook_id)
    audio_artifacts = await client.artifacts.list_audio(notebook_id)
    return [s.id for s in sources] + [a.id for a in audio_artifacts]


async def search_clauses(
    client: NotebookLMClient,
    session: AsyncSession,
    notebook_id: str,
    query: str,
    top_k: int = 5,
    embedder: EmbeddingAdapter | None = None,
) -> ClauseSearchResult:
    """Embed ``query``, find the nearest ingested clauses for ``notebook_id``, and
    synthesize an answer from them via the configured chat LLM.
    """
    document_ids = await _notebook_document_ids(client, notebook_id)
    if not document_ids:
        return ClauseSearchResult(
            answer="This notebook has no ingested clauses to search yet — "
            "run 'Ingest Sources' or 'Assess Audio Overview' first."
        )

    embedder = embedder or OllamaEmbeddingAdapter()
    query_vector = (await asyncio.to_thread(embedder.embed, [query]))[0]

    distance = Embedding.embedding.l2_distance(query_vector)
    stmt = (
        select(Clause, distance.label("distance"))
        .join(Embedding, Embedding.clause_id == Clause.external_id)
        .where(Clause.document_id.in_(document_ids))
        .order_by(distance)
        .limit(top_k)
    )
    rows = (await session.execute(stmt)).all()

    matched = [
        MatchedClause(
            clause_id=clause.external_id,
            document_id=clause.document_id,
            text=clause.text,
            distance=dist,
        )
        for clause, dist in rows
    ]
    if not matched:
        return ClauseSearchResult(answer="No matching clauses found for this notebook.")

    setup_dspy_router()
    context = "\n\n".join(f"[{m.document_id}] {m.text}" for m in matched)
    try:
        prediction = dspy.Predict(ClauseSearchAnswerSignature)(question=query, context=context)
        answer = prediction.answer
    except Exception as e:
        logger.warning("Clause-search LLM synthesis failed: %s", e)
        answer = "LLM synthesis unavailable; showing matched clauses only."

    return ClauseSearchResult(answer=answer, matched_clauses=matched)


#: Rank-list depth for each hybrid leg before fusion (RRF only needs the head).
_HYBRID_LEG_LIMIT = 25


def _rrf_fuse(
    rank_lists: list[list[MatchedClause]],
    k: int = 60,
    top_k: int = 8,
) -> list[MatchedClause]:
    """Merge ranked clause lists by Reciprocal Rank Fusion.

    Each clause scores ``Σ 1/(k + rank)`` over every list it appears in
    (1-based ranks), so a clause retrieved by both legs outranks one retrieved
    by a single leg at a comparable position. Ties break on clause id so the
    output is deterministic.
    """
    scores: dict[str, float] = {}
    clauses: dict[str, MatchedClause] = {}
    for ranked in rank_lists:
        for rank, clause in enumerate(ranked, start=1):
            scores[clause.clause_id] = scores.get(clause.clause_id, 0.0) + 1.0 / (k + rank)
            clauses.setdefault(clause.clause_id, clause)
    ranked_ids = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [clauses[cid] for cid in ranked_ids[:top_k]]


async def _keyword_ranked_clauses(
    session: AsyncSession,
    document_ids: list[str],
    query: str,
    limit: int,
) -> list[MatchedClause]:
    """Full-text leg: Postgres ``websearch_to_tsquery`` over ``Clause.text``.

    Matches through the existing ``idx_clauses_tsv`` GIN index, so no migration
    is needed; ranking is ``ts_rank``.
    """
    from sqlalchemy import func

    tsv = func.to_tsvector("english", Clause.text)
    tsq = func.websearch_to_tsquery("english", query)
    stmt = (
        select(Clause)
        .where(Clause.document_id.in_(document_ids))
        .where(tsv.op("@@")(tsq))
        .order_by(func.ts_rank(tsv, tsq).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [
        MatchedClause(clause_id=c.external_id, document_id=c.document_id, text=c.text) for c in rows
    ]


async def _vector_ranked_clauses(
    session: AsyncSession,
    document_ids: list[str],
    query: str,
    limit: int,
    embedder: EmbeddingAdapter | None,
) -> list[MatchedClause]:
    """pgvector leg: same L2-distance join as :func:`search_clauses`.

    Embedding failures (e.g. Ollama down) degrade to an empty leg — the caller
    still gets keyword-only RRF ranking instead of a failed search.
    """
    try:
        embed = embedder or OllamaEmbeddingAdapter()
        query_vector = (await asyncio.to_thread(embed.embed, [query]))[0]
    except Exception as e:
        logger.warning("RRF vector leg skipped — query embedding failed: %s", e)
        return []

    distance = Embedding.embedding.l2_distance(query_vector)
    stmt = (
        select(Clause, distance.label("distance"))
        .join(Embedding, Embedding.clause_id == Clause.external_id)
        .where(Clause.document_id.in_(document_ids))
        .order_by(distance)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        MatchedClause(
            clause_id=clause.external_id,
            document_id=clause.document_id,
            text=clause.text,
            distance=dist,
        )
        for clause, dist in rows
    ]


async def rrf_search(
    session: AsyncSession,
    document_ids: list[str],
    query: str,
    top_k: int = 8,
    k: int = 60,
    embedder: EmbeddingAdapter | None = None,
) -> list[MatchedClause]:
    """Hybrid retrieval: Postgres full-text + pgvector similarity, fused by RRF.

    The two legs are each ranked to a depth of 25 and merged by Reciprocal Rank
    Fusion (``score = Σ 1/(k + rank)``) into one ranked list. This makes no LLM
    call and never invokes ``setup_dspy_router()`` — callers decide what to do
    with the retrieved clauses.
    """
    if not document_ids:
        return []

    keyword_ranked = await _keyword_ranked_clauses(
        session, document_ids, query, limit=_HYBRID_LEG_LIMIT
    )
    vector_ranked = await _vector_ranked_clauses(
        session, document_ids, query, limit=_HYBRID_LEG_LIMIT, embedder=embedder
    )
    return _rrf_fuse([keyword_ranked, vector_ranked], k=k, top_k=top_k)
