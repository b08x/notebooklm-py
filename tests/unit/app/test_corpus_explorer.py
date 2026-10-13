"""Corpus Explorer query layer against the real Postgres (facts 10-20, 31-33, 55, 62).

Every test seeds throwaway runs under a unique notebook id and filters on it,
inside a rolled-back transaction. Postgres unreachable → the fixture FAILS.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import corpus_explorer as ce
from notebooklm._app.fact_checks import record_fact_check, record_not_checkworthy
from notebooklm.db.models import Clause, Topic, TopicRun
from tests._fixtures.corpus_seed import Seeder, nudged, unit_vector
from tests._fixtures.postgres import pg_session  # noqa: F401

B64 = "NsMvbzsVTlHfstpSeMH70+Qn0nTeo4OkzXKd/43HBfE1ksw//KH7RVvrc1xYsVF/4iken9nTH+Nwu"
NUM = "0.273 0.327 0.307 0.404 0.337 0.410 0.373 0.428"


class _Verdict:
    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.confidence = 0.9
        self.probabilities = {verdict: 0.9}
        self.sift_steps = {"stop": "ok"}
        self.citations = [{"url": "https://example.org", "title": "x", "quote": "q"}]
        self.model = "m"


class QueryEmbedder:
    def __init__(self, vec: list[float]) -> None:
        self.vec = vec

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vec for _ in texts]


class DownEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("ollama down")


@pytest.fixture
async def seeded(pg_session: AsyncSession):  # noqa: F811
    s = Seeder(pg_session)
    entity = unit_vector(f"entity-{s.prefix}")
    s.vectors.update(
        {
            "Named entity recognition uses spaCy": entity,
            "Entity recognition with spaCy pipelines": nudged(entity, 0.02),
        }
    )
    s.run_a1 = await s.ingest(
        "a",
        "Named entity recognition uses spaCy|Kernel panics hit the cgroup limit"
        "||The OOM killer picks the largest RSS",
    )
    s.run_a2 = await s.ingest(
        "a",
        "Named entity recognition uses spaCy|Kernel panics hit the cgroup limit|Extra line"
        "||The OOM killer picks the largest RSS",
    )
    s.run_b = await s.ingest(
        "b",
        f"Entity recognition with spaCy pipelines|{B64}|{NUM}",
        params={"kind": "audio", "title": "Audio transcript"},
    )
    return s


async def _ids(session: AsyncSession, document_id: str) -> list[str]:
    rows = await session.execute(
        select(Clause.external_id)
        .where(Clause.document_id == document_id)
        .order_by(Clause.run_id.desc(), Clause.sentence_index)
    )
    return list(rows.scalars())


def _nb(s: Seeder, **kw) -> ce.CorpusFilters:
    return ce.CorpusFilters(notebook_ids=[s.notebook], **kw)


@pytest.mark.asyncio
async def test_hybrid_search_reports_leg_ranks(seeded: Seeder) -> None:
    out = await ce.search(
        seeded.session,
        "entity recognition spaCy",
        filters=_nb(seeded),
        embedder=QueryEmbedder(unit_vector(f"entity-{seeded.prefix}")),
    )
    assert out["vector_leg_ok"] is True
    top = out["hits"][0]
    assert top["text"] == "Named entity recognition uses spaCy"
    assert top["kw_rank"] is not None and top["vec_rank"] == 1
    assert top["score"] == pytest.approx(1 / (60 + top["kw_rank"]) + 1 / 61)
    # Inactive run a1 is excluded by default.
    assert all(h["run_id"] != seeded.run_a1 for h in out["hits"])
    vec_only = [h for h in out["hits"] if h["kw_rank"] is None]
    assert vec_only and all(h["vec_rank"] for h in vec_only)


@pytest.mark.asyncio
async def test_search_modes(seeded: Seeder) -> None:
    kw = await ce.search(seeded.session, "kernel", mode="keyword", filters=_nb(seeded))
    assert [h["text"] for h in kw["hits"]] == ["Kernel panics hit the cgroup limit"]
    assert kw["hits"][0]["vec_rank"] is None
    vec = await ce.search(
        seeded.session,
        "anything",
        mode="vector",
        filters=_nb(seeded),
        embedder=QueryEmbedder(unit_vector(f"entity-{seeded.prefix}")),
        top_k=2,
    )
    assert {h["kw_rank"] for h in vec["hits"]} == {None}
    assert len(vec["hits"]) == 2
    with pytest.raises(ValueError):
        await ce.search(seeded.session, "x", mode="bogus", filters=_nb(seeded))


@pytest.mark.asyncio
async def test_embedder_down_degrades_to_keyword(seeded: Seeder) -> None:
    out = await ce.search(seeded.session, "kernel", filters=_nb(seeded), embedder=DownEmbedder())
    assert out["vector_leg_ok"] is False
    assert [h["text"] for h in out["hits"]] == ["Kernel panics hit the cgroup limit"]


@pytest.mark.asyncio
async def test_browse_keyset_pagination_and_total(seeded: Seeder) -> None:
    page1 = await ce.browse(seeded.session, _nb(seeded), limit=3)
    assert page1["total"] == 7  # run a2 (4) + run b (3)
    assert len(page1["items"]) == 3 and page1["next_cursor"] == page1["items"][-1]["id"]
    page2 = await ce.browse(seeded.session, _nb(seeded), cursor=page1["next_cursor"], limit=10)
    assert len(page2["items"]) == 4 and page2["next_cursor"] is None
    ids = [r["id"] for r in page1["items"] + page2["items"]]
    assert ids == sorted(ids)
    everything = await ce.browse(seeded.session, _nb(seeded, active_only=False), limit=50)
    assert everything["total"] == 10


@pytest.mark.asyncio
async def test_filters_and_facets(seeded: Seeder) -> None:
    s = seeded
    session = s.session
    ids_b = await _ids(session, s.doc("b"))
    await record_fact_check(
        session, ids_b[0], _Verdict("supported"), job_id=None, trace_id=None, latency_ms=1
    )
    await record_not_checkworthy(session, ids_b[1], job_id=None, trace_id=None)

    quality = await ce.browse(session, _nb(s, quality=["base64"]))
    assert [r["text"] for r in quality["items"]] == [B64]
    assert quality["items"][0]["quality"] == "base64"
    numeric = await ce.browse(session, _nb(s, quality=["numeric_table"]))
    assert [r["text"] for r in numeric["items"]] == [NUM]

    kinds = await ce.browse(session, _nb(s, kinds=["audio"]))
    assert {r["document_id"] for r in kinds["items"]} == {s.doc("b")}
    assert kinds["items"][0]["kind"] == "audio"

    passed = await ce.browse(session, _nb(s, fact_check=["passed"]))
    assert [r["external_id"] for r in passed["items"]] == [ids_b[0]]
    other = await ce.browse(session, _nb(s, fact_check=["other"]))
    assert [r["external_id"] for r in other["items"]] == [ids_b[1]]

    by_len = await ce.browse(session, _nb(s, min_len=60))
    assert all(r["length"] >= 60 for r in by_len["items"]) and by_len["total"] == 1
    text = await ce.browse(session, _nb(s, text="oom killer"))
    assert by_len["total"] == 1 and text["total"] == 1
    runs = await ce.browse(session, _nb(s, run_ids=[s.run_b], strategies=["split"]))
    assert runs["total"] == 3

    f = await ce.facets(session, _nb(s, quality=["clean"]))
    quality_counts = {i["value"]: i["count"] for i in f["quality"]}
    # Own filter is cleared when counting its facet.
    assert quality_counts == {"clean": 5, "base64": 1, "numeric_table": 1}
    assert {i["value"]: i["count"] for i in f["kind"]} == {"source": 4, "audio": 1}
    assert {i["value"]: i["count"] for i in f["fact_check"]} == {
        "unchecked": 4,
        "passed": 1,
        "other": 0,
        "failed": 0,
    }
    # The notebook facet clears its own filter, so other notebooks may appear too.
    assert {"value": s.notebook, "count": 5} in f["notebook"]
    assert sum(i["count"] for i in f["length"]) == 5
    assert {i["value"] for i in f["document"]} == {s.doc("a"), s.doc("b")}
    # Stored titles ride along under labels.document; untitled documents are omitted.
    assert f["labels"]["document"] == {s.doc("b"): "Audio transcript"}
    assert f["strategy"] == [{"value": "split", "count": 5}]
    assert {i["value"] for i in f["run"]} == {s.run_a2, s.run_b}


@pytest.mark.asyncio
async def test_filters_from_mapping() -> None:
    f = ce.CorpusFilters.from_mapping(
        {
            "notebook_ids": "a,b",
            "run_ids": ["1", 2],
            "min_len": "5",
            "has_near_duplicate": "true",
            "active_only": "false",
            "text": "x",
            "bogus": 1,
            "kinds": None,
        }
    )
    assert f.notebook_ids == ["a", "b"] and f.run_ids == [1, 2] and f.min_len == 5
    assert f.has_near_duplicate is True and f.active_only is False and f.text == "x"
    assert ce.CorpusFilters.from_mapping(None) == ce.CorpusFilters()


@pytest.mark.asyncio
async def test_chunk_detail(seeded: Seeder) -> None:
    s = seeded
    ids = await _ids(s.session, s.doc("a"))
    kernel = ids[1]
    detail = await ce.chunk_detail(s.session, kernel)
    assert detail["text"] == "Kernel panics hit the cgroup limit"
    parent = detail["parent"]
    assert parent["text"][parent["child_start"] : parent["child_end"]] == detail["text"]
    assert parent["n_children"] == 3
    assert [c["text"] for c in detail["context"]["before"]] == [
        "Named entity recognition uses spaCy"
    ]
    assert [c["text"] for c in detail["context"]["after"]] == [
        "Extra line",
        "The OOM killer picks the largest RSS",
    ]
    assert {"text": "Kernel", "label": "PROPN"} in detail["entities"]
    assert detail["sfl"] is None and detail["latest_fact_check"] is None
    assert detail["run"]["is_active"] is True

    await s.session.execute(
        update(Clause)
        .where(Clause.external_id == kernel)
        .values(sfl={"tenor": {"formality": "informal"}, "mood": "declarative"})
    )
    await record_fact_check(
        s.session, kernel, _Verdict("contradicted"), job_id="j", trace_id="t", latency_ms=3
    )
    detail = await ce.chunk_detail(s.session, kernel)
    assert detail["sfl"]["interpersonal"]["tenor"] == ["formality: informal"]
    assert detail["latest_fact_check"]["verdict"] == "contradicted"
    assert detail["fact_check"] == "failed"

    with pytest.raises(ce.ChunkNotFoundError):
        await ce.chunk_detail(s.session, "missing:0:0")


@pytest.mark.asyncio
async def test_neighbors_and_near_duplicates(seeded: Seeder) -> None:
    s = seeded
    target = (await _ids(s.session, s.doc("a")))[0]
    near = await ce.neighbors(s.session, target, k=3)
    assert near[0]["text"] == "Entity recognition with spaCy pipelines"
    assert near[0]["near_duplicate"] is True and near[0]["distance"] < ce.NEAR_DUP_L2
    assert all(not n["near_duplicate"] for n in near[1:])
    assert [n["distance"] for n in near] == sorted(n["distance"] for n in near)
    # The older run of the same document (an exact copy) is skipped.
    assert all(n["run_id"] != s.run_a1 for n in near)

    dupes = await ce.browse(s.session, _nb(s, has_near_duplicate=True))
    assert {r["text"] for r in dupes["items"]} == {
        "Named entity recognition uses spaCy",
        "Entity recognition with spaCy pipelines",
    }
    with pytest.raises(ce.ChunkNotFoundError):
        await ce.neighbors(s.session, "missing:0:0")


@pytest.mark.asyncio
async def test_runs_stats_and_new_count(seeded: Seeder) -> None:
    s = seeded
    runs = await ce.runs(s.session, notebook_id=s.notebook)
    assert [r["id"] for r in runs] == [s.run_b, s.run_a2, s.run_a1]
    assert runs[0]["kind"] == "audio" and runs[0]["n_children"] == 3
    assert {r["is_active"] for r in runs[1:]} == {True, False}
    assert all(k in runs[0] for k in ("strategy", "n_parents", "mean_len", "p95_len"))
    active = await ce.runs(s.session, document_id=s.doc("a"), active_only=True)
    assert [r["id"] for r in active] == [s.run_a2]

    st = await ce.stats(s.session, _nb(s))
    assert (st["clauses"], st["documents"], st["runs"], st["parents"]) == (7, 2, 2, 3)
    assert st["max_clause_id"] >= st["filtered_max_clause_id"] > 0

    since = st["filtered_max_clause_id"]
    assert await ce.count_new_since(s.session, since, _nb(s)) == 0
    await s.ingest("c", "fresh one|fresh two")
    assert await ce.count_new_since(s.session, since, _nb(s)) == 2


@pytest.mark.asyncio
async def test_map_points_color_by_document_then_topic(seeded: Seeder) -> None:
    s = seeded
    out = await ce.map_points(s.session, filters=_nb(s))
    assert out["color_by"] == "document"
    assert out["method"] == "pca"
    assert len(out["points"]) == 7
    p = out["points"][0]
    assert set(p) >= {"x", "y", "external_id", "document_id"}

    tr = TopicRun(params={}, n_docs=1, n_topics=1)
    s.session.add(tr)
    await s.session.flush()
    topic = Topic(run_id=tr.id, topic_number=0, label="kernels", keywords=[], size=1)
    s.session.add(topic)
    await s.session.flush()
    await s.session.execute(
        update(Clause).where(Clause.document_id == s.doc("a")).values(topic_id=topic.id)
    )
    out = await ce.map_points(s.session, filters=_nb(s), method="umap")
    assert out["color_by"] == "topic"
    assert {p["topic"] for p in out["points"]} == {"kernels", None}


@pytest.mark.asyncio
async def test_map_cache_for_unfiltered_map(pg_session: AsyncSession) -> None:  # noqa: F811
    ce._MAP_CACHE.clear()
    first = await ce.map_points(pg_session)
    second = await ce.map_points(pg_session)
    assert first == second
    assert len(ce._MAP_CACHE) == 1


def test_project_small_inputs() -> None:
    empty, method = ce._project([], "pca")
    assert empty.shape == (0, 2)
    assert method == "pca"
    one, method = ce._project([[1.0, 2.0]], "pca")
    assert one.shape == (1, 2)
    assert method == "pca"
    two, method = ce._project([[1.0, 2.0], [2.0, 1.0]], "umap")
    assert two.shape == (2, 2)
    assert method == "pca"  # too few points for UMAP: falls back to PCA


def test_entities_from_handles_bad_shapes() -> None:
    assert ce.entities_from(None, None) == []
    tokens = [{"text": "Ada", "pos": "PROPN"}, {"text": "wrote", "pos": "VERB"}]
    groups = {"noun_chunks": [{"text": "Ada", "root": 0}, {"text": "", "root": 1}]}
    assert ce.entities_from(tokens, groups) == [{"text": "Ada", "label": "PROPN"}]


@pytest.mark.asyncio
async def test_embedder_health_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    out = await ce.embedder_health(timeout=0.5)
    assert out["ok"] is False and "error" in out


@pytest.mark.asyncio
async def test_documents_and_clauses_queries(seeded: Seeder) -> None:
    from notebooklm.db.models import FactCheck

    # 1. documents query
    docs = await ce.documents(seeded.session, _nb(seeded))
    assert len(docs) == 2
    doc_map = {d["document_id"]: d for d in docs}
    doc_a = doc_map[seeded.doc("a")]
    doc_b = doc_map[seeded.doc("b")]
    # doc a has 4 clauses in active run a2
    assert doc_a["clause_count"] == 4
    assert doc_a["tagged_count"] == 0
    assert doc_a["fact_checked_count"] == 0
    # doc b has 3 clauses and audio kind -> transcript
    assert doc_b["clause_count"] == 3
    assert doc_b["file_type"] == "transcript"

    # 2. Tag some clauses
    a_ids = await _ids(seeded.session, seeded.doc("a"))
    await seeded.session.execute(
        update(Clause).where(Clause.external_id == a_ids[0]).values(sfl={"mood": "declarative"})
    )
    # Add a fact check
    seeded.session.add(
        FactCheck(
            clause_external_id=a_ids[0],
            verdict="supported",
            confidence=0.95,
        )
    )
    await seeded.session.flush()

    docs_after = await ce.documents(seeded.session, _nb(seeded))
    assert docs_after[0]["tagged_count"] == 1
    assert docs_after[0]["fact_checked_count"] == 1

    # 3. document_clauses query
    detail = await ce.document_clauses(seeded.session, seeded.doc("a"))
    assert detail["document_id"] == seeded.doc("a")
    assert len(detail["chunks"]) >= 1
    # Check parent chunks have clauses
    first_chunk = detail["chunks"][0]
    assert "clauses" in first_chunk
    assert first_chunk["clause_count"] >= 1
    first_clause = first_chunk["clauses"][0]
    assert first_clause["external_id"] == a_ids[0]
    assert first_clause["has_sfl"] is True
    assert first_clause["fact_check"] == "supported"

    # 4. Unknown document raises DocumentNotFoundError
    with pytest.raises(ce.DocumentNotFoundError):
        await ce.document_clauses(seeded.session, "does_not_exist")
