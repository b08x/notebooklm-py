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
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import dspy
from sqlalchemy import Select, func, select

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

#: Search modes accepted by :func:`ranked_search`.
SEARCH_MODES = ("keyword", "vector", "hybrid")

#: Narrows a leg's ``select(Clause ...)`` statement (joins + where clauses).
Scope = Callable[[Select[Any]], Select[Any]]


@dataclass
class RankedClause(MatchedClause):
    """A fused hit with its per-leg ranks (1-based; ``None`` = absent from that leg)."""

    kw_rank: int | None = None
    vec_rank: int | None = None
    score: float = 0.0


@dataclass
class RankedSearch:
    """Fused hits plus whether the vector leg actually ran."""

    hits: list[RankedClause]
    vector_leg_ok: bool
    keyword_count: int = 0
    vector_count: int = 0


def _rrf_scores(rank_lists: list[list[MatchedClause]], k: int) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranked in rank_lists:
        for rank, clause in enumerate(ranked, start=1):
            scores[clause.clause_id] = scores.get(clause.clause_id, 0.0) + 1.0 / (k + rank)
    return scores


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
    scores = _rrf_scores(rank_lists, k)
    clauses: dict[str, MatchedClause] = {}
    for ranked in rank_lists:
        for clause in ranked:
            clauses.setdefault(clause.clause_id, clause)
    ranked_ids = sorted(scores, key=lambda cid: (-scores[cid], cid))
    return [clauses[cid] for cid in ranked_ids[:top_k]]


def fuse_ranked(
    keyword_ranked: list[MatchedClause],
    vector_ranked: list[MatchedClause],
    k: int = 60,
    top_k: int = 8,
) -> list[RankedClause]:
    """RRF-fuse the two legs, keeping each hit's keyword rank, vector rank and score."""
    scores = _rrf_scores([keyword_ranked, vector_ranked], k)
    kw_rank = {c.clause_id: i for i, c in enumerate(keyword_ranked, start=1)}
    vec_rank = {c.clause_id: i for i, c in enumerate(vector_ranked, start=1)}
    by_id: dict[str, MatchedClause] = {}
    for clause in [*vector_ranked, *keyword_ranked]:
        by_id.setdefault(clause.clause_id, clause)
    ranked_ids = sorted(scores, key=lambda cid: (-scores[cid], cid))[:top_k]
    return [
        RankedClause(
            clause_id=cid,
            document_id=by_id[cid].document_id,
            text=by_id[cid].text,
            distance=by_id[cid].distance,
            kw_rank=kw_rank.get(cid),
            vec_rank=vec_rank.get(cid),
            score=scores[cid],
        )
        for cid in ranked_ids
    ]


def _scoped(stmt: Select[Any], document_ids: list[str] | None, scope: Scope | None) -> Select[Any]:
    if document_ids is not None:
        stmt = stmt.where(Clause.document_id.in_(document_ids))
    return scope(stmt) if scope is not None else stmt


async def _keyword_ranked_clauses(
    session: AsyncSession,
    document_ids: list[str] | None,
    query: str,
    limit: int,
    scope: Scope | None = None,
) -> list[MatchedClause]:
    """Full-text leg: Postgres ``websearch_to_tsquery`` over ``Clause.text``.

    Matches through the existing ``idx_clauses_tsv`` GIN index, so no migration
    is needed; ranking is ``ts_rank``. ``document_ids=None`` searches the whole
    corpus (narrowed only by ``scope``).
    """
    tsv = func.to_tsvector("english", Clause.text)
    tsq = func.websearch_to_tsquery("english", query)
    stmt = select(Clause).where(tsv.op("@@")(tsq))
    stmt = _scoped(stmt, document_ids, scope)
    stmt = stmt.order_by(func.ts_rank(tsv, tsq).desc(), Clause.id).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        MatchedClause(clause_id=c.external_id, document_id=c.document_id, text=c.text) for c in rows
    ]


async def _embed_query(query: str, embedder: EmbeddingAdapter | None) -> list[float]:
    embed = embedder or OllamaEmbeddingAdapter()
    return (await asyncio.to_thread(embed.embed, [query]))[0]


async def _vector_ranked_clauses(
    session: AsyncSession,
    document_ids: list[str] | None,
    query: str,
    limit: int,
    embedder: EmbeddingAdapter | None,
    scope: Scope | None = None,
) -> list[MatchedClause] | None:
    """pgvector leg: same L2-distance join as :func:`search_clauses`.

    Returns ``None`` when the query embedding fails (e.g. Ollama down), so the
    caller can still serve keyword-only RRF ranking and report the missing leg.
    """
    try:
        query_vector = await _embed_query(query, embedder)
    except Exception as e:
        logger.warning("RRF vector leg skipped — query embedding failed: %s", e)
        return None

    distance = Embedding.embedding.l2_distance(query_vector)
    stmt = select(Clause, distance.label("distance")).join(
        Embedding, Embedding.clause_id == Clause.external_id
    )
    stmt = _scoped(stmt, document_ids, scope)
    stmt = stmt.order_by(distance, Clause.id).limit(limit)
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


async def ranked_search(
    session: AsyncSession,
    query: str,
    *,
    document_ids: list[str] | None = None,
    mode: str = "hybrid",
    top_k: int = 8,
    k: int = 60,
    embedder: EmbeddingAdapter | None = None,
    scope: Scope | None = None,
    leg_limit: int = _HYBRID_LEG_LIMIT,
) -> RankedSearch:
    """Keyword, vector or hybrid-RRF search with a per-leg rank breakdown.

    LLM-free: never calls ``setup_dspy_router()`` / ``dspy.configure()``, so the
    REST server may call it from any request concurrently.
    """
    if mode not in SEARCH_MODES:
        raise ValueError(f"Unknown search mode {mode!r}; expected one of {SEARCH_MODES}")
    keyword_ranked: list[MatchedClause] = []
    vector_ranked: list[MatchedClause] = []
    vector_ok = True
    if mode in ("keyword", "hybrid"):
        keyword_ranked = await _keyword_ranked_clauses(
            session, document_ids, query, limit=max(leg_limit, top_k), scope=scope
        )
    if mode in ("vector", "hybrid"):
        legs = await _vector_ranked_clauses(
            session,
            document_ids,
            query,
            limit=max(leg_limit, top_k),
            embedder=embedder,
            scope=scope,
        )
        vector_ok = legs is not None
        vector_ranked = legs or []
    return RankedSearch(
        hits=fuse_ranked(keyword_ranked, vector_ranked, k=k, top_k=top_k),
        vector_leg_ok=vector_ok,
        keyword_count=len(keyword_ranked),
        vector_count=len(vector_ranked),
    )


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
    result = await ranked_search(
        session, query, document_ids=document_ids, top_k=top_k, k=k, embedder=embedder
    )
    return list(result.hits)
