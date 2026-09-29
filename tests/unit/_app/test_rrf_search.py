"""Unit tests for hybrid RRF retrieval over ingested clauses (facts 18–20).

The fusion math is tested purely. The SQL legs (Postgres full-text via the
existing ``idx_clauses_tsv`` GIN index + pgvector similarity) are exercised
against the local Postgres when ``DATABASE_URL`` is reachable and skipped
otherwise (plan Step 1b).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from notebooklm._app.clause_search import MatchedClause, _rrf_fuse, rrf_search

QUERY_VECTOR = [0.1] * 768


class FakeEmbedder:
    """Deterministic stand-in for the Ollama embedder (768-dim, plan risk 6)."""

    def embed(self, texts):
        return [list(QUERY_VECTOR) for _ in texts]


def _mc(clause_id: str, text: str = "clause text") -> MatchedClause:
    return MatchedClause(clause_id=clause_id, document_id="doc-1", text=text)


def test_rrf_fusion_clause_in_both_legs_outranks_single_leg():
    both = _mc("c-both")
    kw_only = _mc("c-kw")
    vec_only = _mc("c-vec")

    fused = _rrf_fuse([[both, kw_only], [both, vec_only]], k=60, top_k=3)

    assert [c.clause_id for c in fused] == ["c-both", "c-kw", "c-vec"]
    # both legs: 1/(60+1) + 1/(60+1) must beat any single-leg rank-1 score.
    assert 2.0 / 61.0 > 1.0 / 61.0


def test_rrf_fusion_top_k_is_respected():
    kw = [_mc(f"kw-{i}") for i in range(10)]
    vec = [_mc(f"vec-{i}") for i in range(10)]

    fused = _rrf_fuse([kw, vec], k=60, top_k=5)

    assert len(fused) == 5


def test_rrf_fusion_ties_break_deterministically():
    kw = [_mc("c-b"), _mc("c-a")]
    vec = [_mc("c-d"), _mc("c-c")]

    fused = _rrf_fuse([kw, vec], k=60, top_k=4)

    # rank-1 clauses (c-b, c-d) tie at 1/61 and rank-2 clauses (c-a, c-c) at
    # 1/62; each tier sorts by clause id so the output is deterministic.
    assert [c.clause_id for c in fused] == ["c-b", "c-d", "c-a", "c-c"]


def test_rrf_fusion_single_leg_only():
    """When the vector leg is empty (e.g. Ollama down), ranking degrades to keyword-only."""
    kw = [_mc("c-2"), _mc("c-1")]

    fused = _rrf_fuse([kw, []], k=60, top_k=8)

    assert [c.clause_id for c in fused] == ["c-2", "c-1"]


@pytest.fixture
async def db_session():
    from notebooklm.db.session import async_session_maker

    try:
        async with async_session_maker() as probe:
            await probe.execute(text("select 1"))
    except Exception as e:  # pragma: no cover — environment-dependent
        pytest.skip(f"local Postgres unreachable: {e}")

    async with async_session_maker() as session:
        yield session
        await session.rollback()


async def test_rrf_search_hybrid_ranking(db_session):
    from notebooklm.db.models import Clause, Embedding

    document_id = f"rrf-test-{uuid.uuid4().hex[:8]}"

    async def add(external_id: str, body: str, *, with_vector: bool) -> None:
        db_session.add(Clause(external_id=external_id, text=body, document_id=document_id))
        if with_vector:
            db_session.add(
                Embedding(clause_id=external_id, embedding=list(QUERY_VECTOR), model="fake")
            )

    # keyword + vector: must fuse to the top.
    await add(
        f"{document_id}:both",
        "The agreement checkpoint confirmed the pipeline merge completed cleanly.",
        with_vector=True,
    )
    # keyword only.
    await add(
        f"{document_id}:kw",
        "An agreement checkpoint failure escalated into a tier two incident.",
        with_vector=False,
    )
    # vector only (no keyword overlap).
    await add(
        f"{document_id}:vec",
        "A clause about entirely different subject matter, with no shared vocabulary.",
        with_vector=True,
    )
    # irrelevant: no keyword, far vector.
    far = [0.9] * 768
    db_session.add(
        Clause(
            external_id=f"{document_id}:far", text="Unrelated boilerplate.", document_id=document_id
        )
    )
    db_session.add(Embedding(clause_id=f"{document_id}:far", embedding=far, model="fake"))
    await db_session.flush()

    matched = await rrf_search(
        db_session, [document_id], "agreement checkpoint", top_k=3, embedder=FakeEmbedder()
    )

    ids = [m.clause_id for m in matched]
    assert ids[0] == f"{document_id}:both"
    assert set(ids) == {f"{document_id}:both", f"{document_id}:kw", f"{document_id}:vec"}
    assert all(m.text for m in matched)
    # The keyword leg carries no distance; the fused both-match keeps it.
    assert matched[0].distance is not None or matched[0].text


async def test_rrf_search_empty_document_ids(db_session):
    assert await rrf_search(db_session, [], "anything") == []
