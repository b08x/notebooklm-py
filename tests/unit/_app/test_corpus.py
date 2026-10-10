"""``_app.corpus`` read queries against the local Postgres (rolled back)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import corpus
from notebooklm._preprocessing.chunking import ChildChunk, ChunkResult, ChunkStats, ParentChunk
from notebooklm._preprocessing.features import ClauseFeatures
from notebooklm._preprocessing.ingestion import IngestionService
from notebooklm.db.models import Clause, FactCheck, Topic, TopicRun
from tests._fixtures.postgres import pg_session  # noqa: F401


class _Split:
    name, version = "split", "1"
    params: dict = {}

    def chunk(self, text: str) -> ChunkResult:
        parents, offset = [], 0
        for block in text.split("||"):
            kids, pos = [], offset
            for piece in block.split("|"):
                kids.append(ChildChunk(piece, pos, pos + len(piece)))
                pos += len(piece) + 1
            parents.append(ParentChunk(block, offset, offset + len(block), kids))
            offset += len(block) + 2
        return ChunkResult(parents, ChunkStats())


def _service() -> IngestionService:
    embedder = MagicMock()
    embedder.embed = MagicMock(side_effect=lambda b: [[0.1] * 768 for _ in b])
    return IngestionService(
        MagicMock(),
        embedder=embedder,
        strategy=_Split(),
        features=lambda texts: [ClauseFeatures([{"text": t}], {}, 0) for t in texts],
    )


@pytest.fixture
async def seeded(pg_session: AsyncSession):  # noqa: F811
    svc = _service()
    await svc.ingest_text(pg_session, "doc-a", "a1|a2||a3", notebook_id="nb-c")
    await svc.ingest_text(pg_session, "doc-a", "a1|a2|a2b||a3", notebook_id="nb-c")
    await svc.ingest_text(pg_session, "doc-b", "b1", notebook_id="nb-c")
    await svc.ingest_text(pg_session, "doc-z", "z1", notebook_id="nb-other")
    return pg_session


@pytest.mark.asyncio
async def test_active_runs_and_parents(seeded) -> None:
    runs = await corpus.active_runs(seeded, "nb-c")
    assert [(r["document_id"], r["n_children"]) for r in runs] == [("doc-a", 4), ("doc-b", 1)]
    parents = await corpus.parents(seeded, runs[0]["id"])
    assert [(p["index"], p["text"], p["n_children"]) for p in parents] == [
        (0, "a1|a2|a2b", 3),
        (1, "a3", 1),
    ]


@pytest.mark.asyncio
async def test_document_runs_newest_first(seeded) -> None:
    runs = await corpus.document_runs(seeded, "doc-a")
    assert [r["is_active"] for r in runs] == [True, False]
    assert runs[0]["n_children"] == 4 and runs[1]["n_children"] == 3


@pytest.mark.asyncio
async def test_children_carry_features_sfl_and_topic(seeded) -> None:
    runs = await corpus.active_runs(seeded, "nb-c")
    parent = (await corpus.parents(seeded, runs[0]["id"]))[0]
    trun = TopicRun(params={}, n_docs=1, n_topics=1)
    seeded.add(trun)
    await seeded.flush()
    topic = Topic(run_id=trun.id, topic_number=0, label="0_music", keywords=["music"], size=1)
    seeded.add(topic)
    await seeded.flush()
    await seeded.execute(
        update(Clause)
        .where(Clause.parent_id == parent["id"], Clause.text == "a1")
        .values(sfl={"mood": "declarative"}, topic_id=topic.id)
    )
    kids = await corpus.children(seeded, parent["id"])
    assert [k["text"] for k in kids] == ["a1", "a2", "a2b"]
    assert kids[0]["sfl"] == {"mood": "declarative"} and kids[0]["topic"] == "0_music"
    assert kids[0]["tokens"] == [{"text": "a1"}]
    assert kids[1]["topic"] is None


@pytest.mark.asyncio
async def test_claims_newest_verdict_and_filter(seeded) -> None:
    runs = await corpus.active_runs(seeded, "nb-c")
    parent = (await corpus.parents(seeded, runs[0]["id"]))[0]
    kids = await corpus.children(seeded, parent["id"])
    first, second = kids[0]["external_id"], kids[1]["external_id"]
    seeded.add_all(
        [
            FactCheck(clause_external_id=first, verdict="unverifiable"),
            FactCheck(clause_external_id=first, verdict="contradicted", confidence=0.9),
            FactCheck(clause_external_id=second, verdict="supported", trace_id="t" * 32),
        ]
    )
    await seeded.flush()
    claims = await corpus.claims(seeded, "nb-c")
    assert [(c["text"], c["verdict"]) for c in claims] == [
        ("a1", "contradicted"),
        ("a2", "supported"),
    ]
    assert claims[0]["parent_text"] == "a1|a2|a2b" and claims[0]["confidence"] == 0.9
    only = await corpus.claims(seeded, "nb-c", "contradicted")
    assert [c["external_id"] for c in only] == [first]
    assert await corpus.claims(seeded, "nb-other") == []
