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
    distance: float


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
