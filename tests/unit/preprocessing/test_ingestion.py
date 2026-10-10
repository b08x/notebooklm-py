"""IngestionService against the local Postgres (rolled back after each test).

These tests FAIL, never skip, when Postgres is unreachable: ingestion writes
runs, parents, children and embeddings that only a real schema can validate.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from notebooklm._preprocessing.chunking import ChildChunk, ChunkResult, ChunkStats, ParentChunk
from notebooklm._preprocessing.features import ClauseFeatures
from notebooklm._preprocessing.ingestion import (
    PROVIDED_STRATEGY,
    IngestionService,
    resolve_notebook_context,
)
from notebooklm.db.models import ChunkRun, Clause, Embedding
from notebooklm.db.models import ParentChunk as ParentChunkRow
from notebooklm.db.session import DATABASE_URL


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        conn = await engine.connect()
    except Exception as e:  # pragma: no cover - environment failure path
        await engine.dispose()
        pytest.fail(f"Postgres unreachable at {DATABASE_URL}: {e}", pytrace=False)
    trans = await conn.begin()
    sess = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield sess
    finally:
        await sess.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()


class _Strategy:
    """Parents split on '||'; children split on '|' inside each parent."""

    name = "fake"
    version = "7"

    def __init__(self, vectors: bool = False) -> None:
        self.vectors = vectors

    @property
    def params(self) -> dict:
        return {"k": 1}

    def chunk(self, text: str) -> ChunkResult:
        parents = []
        offset = 0
        for block in text.split("||"):
            children = []
            pos = offset
            for piece in block.split("|"):
                vec = [0.5] * 768 if self.vectors else None
                children.append(ChildChunk(piece, pos, pos + len(piece), vec))
                pos += len(piece) + 1
            parents.append(ParentChunk(block, offset, offset + len(block), children))
            offset += len(block) + 2
        return ChunkResult(parents=parents, stats=ChunkStats(entity_vetoes=3, extra={"x": True}))


def _features(texts):
    return [
        ClauseFeatures(
            tokens=[{"text": t}], groups={"noun_chunks": [], "clauses": []}, root_index=0
        )
        for t in texts
    ]


def _embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed = MagicMock(side_effect=lambda batch: [[0.1] * 768 for _ in batch])
    return embedder


def _client(content: str = "", summary: str = "") -> MagicMock:
    client = MagicMock()
    client.sources.get_fulltext = AsyncMock(return_value=SimpleNamespace(content=content))
    client.sources.get_guide = AsyncMock(return_value=SimpleNamespace(summary=""))
    client.notebooks.get_summary = AsyncMock(return_value=summary)
    return client


def _service(client=None, **kw) -> IngestionService:
    kw.setdefault("embedder", _embedder())
    kw.setdefault("strategy", _Strategy())
    return IngestionService(client or _client(), features=_features, **kw)


async def _count(session, model, *where) -> int:
    stmt = select(func.count()).select_from(model).where(*where)
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_ingest_text_writes_run_parents_children_embeddings(session) -> None:
    n = await _service().ingest_text(session, "doc-t", "a|bb||ccc", notebook_id="nb-1")
    assert n == 3

    run = (
        await session.execute(select(ChunkRun).where(ChunkRun.document_id == "doc-t"))
    ).scalar_one()
    assert (run.strategy, run.chunker_version, run.notebook_id) == ("fake", "7", "nb-1")
    assert (run.n_parents, run.n_children, run.entity_vetoes, run.is_active) == (2, 3, 3, True)
    assert run.params == {"k": 1, "x": True, "embed_context": False}
    assert len(run.source_hash) == 64
    assert run.mean_len == pytest.approx(2.0)

    clauses = (
        (await session.execute(select(Clause).where(Clause.run_id == run.id).order_by(Clause.id)))
        .scalars()
        .all()
    )
    assert [c.external_id for c in clauses] == [f"doc-t:{run.id}:{i}" for i in range(3)]
    assert all(c.parent_id is not None for c in clauses)
    assert clauses[0].tokens == [{"text": "a"}]
    parents = (
        (await session.execute(select(ParentChunkRow).where(ParentChunkRow.run_id == run.id)))
        .scalars()
        .all()
    )
    assert {p.text for p in parents} == {"a|bb", "ccc"}
    ids = [c.external_id for c in clauses]
    assert await _count(session, Embedding, Embedding.clause_id.in_(ids)) == 3


@pytest.mark.asyncio
async def test_second_run_keeps_first_and_flips_active(session) -> None:
    service = _service()
    await service.ingest_text(session, "doc-r", "a|b")
    await service.ingest_text(session, "doc-r", "a|b||c")
    stmt = select(ChunkRun).where(ChunkRun.document_id == "doc-r").order_by(ChunkRun.id)
    runs = (await session.execute(stmt)).scalars().all()
    assert [r.is_active for r in runs] == [False, True]
    assert await _count(session, Clause, Clause.document_id == "doc-r") == 5


@pytest.mark.asyncio
async def test_strategy_vectors_reused_only_without_context(session) -> None:
    embedder = _embedder()
    service = _service(embedder=embedder, strategy=_Strategy(vectors=True))
    await service.ingest_text(session, "doc-v", "a|b")
    embedder.embed.assert_not_called()
    await service.ingest_text(session, "doc-v2", "a|b", context="Ctx")
    embedder.embed.assert_called_once_with(["Ctx\n\na", "Ctx\n\nb"])


@pytest.mark.asyncio
async def test_ingest_chunks_is_one_to_one_and_returns_ids(session) -> None:
    result = await _service().ingest_chunks(session, "art-1", ["Turn one.", "  ", "Turn two."])
    assert result is not None
    assert result.n_children == 2
    run = (await session.execute(select(ChunkRun).where(ChunkRun.id == result.run_id))).scalar_one()
    assert (run.strategy, run.n_parents, run.n_children) == (PROVIDED_STRATEGY, 2, 2)
    stmt = select(Clause.text).where(Clause.external_id.in_(result.external_ids))
    assert sorted((await session.execute(stmt)).scalars()) == ["Turn one.", "Turn two."]


@pytest.mark.asyncio
async def test_blank_input_writes_nothing(session) -> None:
    embedder = _embedder()
    assert await _service(embedder=embedder).ingest_chunks(session, "art-0", ["", " "]) is None
    embedder.embed.assert_not_called()
    assert await _count(session, ChunkRun, ChunkRun.document_id == "art-0") == 0


@pytest.mark.asyncio
async def test_embedding_batches_and_progress(session) -> None:
    embedder = _embedder()
    progress: list[tuple[int, int]] = []
    service = _service(embedder=embedder, embed_batch_size=2)
    await service.ingest_text(
        session, "doc-b", "a|b|c", on_progress=lambda d, t: progress.append((d, t))
    )
    assert [len(c.args[0]) for c in embedder.embed.call_args_list] == [2, 1]
    assert progress == [(2, 3), (3, 3)]


@pytest.mark.asyncio
async def test_vector_count_mismatch_raises(session) -> None:
    embedder = MagicMock()
    embedder.embed = MagicMock(return_value=[[0.1] * 768])
    with pytest.raises(ValueError, match="mismatch"):
        await _service(embedder=embedder).ingest_text(session, "doc-m", "a|b")


@pytest.mark.asyncio
async def test_source_prefixes_notebook_summary_by_default(session) -> None:
    embedder = _embedder()
    client = _client(content="First.", summary="Earnings call transcript.")
    await _service(client, embedder=embedder).ingest_source(session, "nb-1", "src-ctx")
    client.notebooks.get_summary.assert_awaited_once_with("nb-1")
    embedder.embed.assert_called_once_with(["Earnings call transcript.\n\nFirst."])


@pytest.mark.asyncio
async def test_source_context_disabled_or_overridden(session) -> None:
    embedder = _embedder()
    client = _client(content="First.", summary="S")
    service = _service(client, embedder=embedder, use_notebook_context=False)
    await service.ingest_source(session, "nb-1", "src-a")
    client.notebooks.get_summary.assert_not_awaited()
    await service.ingest_source(session, "nb-1", "src-b", context="Custom.")
    await service.ingest_source(session, "nb-1", "src-c", context="")
    assert [c.args[0] for c in embedder.embed.call_args_list] == [
        ["First."],
        ["Custom.\n\nFirst."],
        ["First."],
    ]


@pytest.mark.asyncio
async def test_real_spacy_features_stored(session) -> None:
    service = IngestionService(_client(), embedder=_embedder(), strategy=_Strategy())
    await service.ingest_text(session, "doc-s", "The model asserts that retrieval helps.")
    stmt = select(Clause).where(Clause.document_id == "doc-s")
    clause = (await session.execute(stmt)).scalar_one()
    assert clause.tokens is not None
    assert set(clause.tokens[0]) == {"text", "lemma", "pos", "tag", "dep", "head", "morph"}
    assert clause.root_index is not None
    assert clause.tokens[clause.root_index]["dep"] == "ROOT"
    assert {"noun_chunks", "clauses"} <= set(clause.groups)


@pytest.mark.asyncio
async def test_resolve_notebook_context_variants() -> None:
    client = MagicMock()
    client.notebooks.get_summary = AsyncMock(return_value="  Q3 earnings.  ")
    assert await resolve_notebook_context(client, "nb") == "Q3 earnings."
    client.notebooks.get_summary = AsyncMock(return_value="")
    assert await resolve_notebook_context(client, "nb") is None
    client.notebooks.get_summary = AsyncMock(side_effect=RuntimeError("x"))
    assert await resolve_notebook_context(client, "nb") is None
