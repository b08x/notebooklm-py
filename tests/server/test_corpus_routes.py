"""``/v1/corpus`` routes against the real Postgres (facts 1-4, 9-33, 45, 49-57, 60-63).

Seed data is committed under a per-test uuid prefix (the routes open their own
sessions) and deleted afterwards. Postgres unreachable → the seed step FAILS.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import dspy
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from notebooklm._app import corpus_explorer
from notebooklm.db.session import async_session_maker
from notebooklm.server import _static
from notebooklm.server._corpus import CorpusServices
from notebooklm.server.app import create_app

from ._corpus_env import HEADERS, FakeNotebooks, _health, _nb, _sse, _wait

# ---------------------------------------------------------------------------
# Auth + availability
# ---------------------------------------------------------------------------


def test_every_corpus_route_requires_token(env: Any) -> None:
    paths = {
        (route.path, method)
        for route in env.app.routes
        if getattr(route, "path", "").startswith("/v1/corpus")
        for method in getattr(route, "methods", ())
    }
    assert len(paths) >= 29
    anon = TestClient(env.app, client=("127.0.0.1", 5555), raise_server_exceptions=False)
    for path, method in sorted(paths):
        url = (
            path.replace("{external_id}", "x")
            .replace("{document_id}", "x")
            .replace("{run_id}", "x")
            .replace("{job_id}", "x")
            .replace("{artifact_id}", "x")
            .replace("{action}", "pause")
        )
        resp = anon.request(method, url, headers={"Host": "127.0.0.1"})
        assert resp.status_code == 401, (method, path, resp.status_code)


def test_database_unreachable_is_503(seeded: Any) -> None:
    bad = async_sessionmaker(
        create_async_engine(
            "postgresql+asyncpg://postgres:postgres@127.0.0.1:1/x", poolclass=NullPool
        ),
        expire_on_commit=False,
    )
    services = CorpusServices(session_maker=bad, configure_llm=False, embedder_health=_health)
    app = create_app(corpus_services=services, client_factory=lambda: _never())
    with TestClient(app, headers=HEADERS, client=("127.0.0.1", 5555)) as http:
        for method, url, body in [
            ("GET", "/v1/corpus/stats", None),
            ("GET", "/v1/corpus/chunks", None),
            ("POST", "/v1/corpus/search", {"query": "x"}),
            ("POST", "/v1/corpus/delete/preview", {"level": "clause", "ids": ["x"]}),
        ]:
            resp = http.request(method, url, json=body)
            assert resp.status_code == 503, url
            assert resp.json()["error"]["category"] == "database_unreachable"
        health = http.get("/v1/corpus/health").json()
        assert health["postgres"]["ok"] is False


@asynccontextmanager
async def _never() -> Any:
    raise ValueError("Authentication expired or invalid. Run 'notebooklm login'.")
    yield  # pragma: no cover


def test_ui_is_served_with_spa_fallback(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<!doctype html><div id=root>Corpus Explorer</div>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app = FastAPI()
    _static.mount_ui(app, tmp_path)
    http = TestClient(app)
    assert "Corpus Explorer" in http.get("/ui/").text
    assert "Corpus Explorer" in http.get("/ui/fact-check/run/123").text  # client route
    assert http.get("/ui/assets/app.js").text == "console.log(1)"
    assert http.get("/", follow_redirects=False).headers["location"] == "/ui/"

    empty = FastAPI()
    _static.mount_ui(empty, tmp_path / "missing")
    assert TestClient(empty).get("/ui/anything").status_code == 503


def test_real_app_mounts_ui_publicly(env: Any) -> None:
    resp = env.http.get("/ui/", headers={"Authorization": ""})
    assert resp.status_code in (200, 503)
    if (_static.UI_DIR / "index.html").is_file():
        assert resp.status_code == 200 and '<div id="root">' in resp.text


# ---------------------------------------------------------------------------
# Read routes
# ---------------------------------------------------------------------------


def test_stats_facets_browse(env: Any) -> None:
    nb = f"notebook_ids={env.notebook}&notebook_ids={env.notebook2}"
    st = env.http.get(f"/v1/corpus/stats?{nb}&since=0").json()
    assert st["clauses"] == 5 and st["documents"] == 2 and st["new_since"] == 5
    f = env.http.get(f"/v1/corpus/facets?{nb}").json()
    assert {i["value"]: i["count"] for i in f["kind"]} == {"source": 3, "audio": 2}
    page = env.http.get(f"/v1/corpus/chunks?{nb}&limit=2").json()
    assert page["total"] == 5 and len(page["items"]) == 2 and page["next_cursor"]
    rest = env.http.get(f"/v1/corpus/chunks?{nb}&cursor={page['next_cursor']}").json()
    assert len(rest["items"]) == 3
    audio = env.http.get(f"/v1/corpus/chunks?{nb}&kinds=audio").json()
    assert {r["document_id"] for r in audio["items"]} == {env.doc_b}
    dupes = env.http.get(f"/v1/corpus/chunks?{nb}&has_near_duplicate=true").json()
    assert dupes["total"] == 2
    assert env.http.get("/v1/corpus/chunks?min_len=abc").status_code == 422


def test_search_detail_neighbors(env: Any) -> None:
    out = env.http.post(
        "/v1/corpus/search",
        json={"query": "entity recognition spaCy", "filters": _nb(env), "mode": "hybrid"},
    ).json()
    top = out["hits"][0]
    assert top["kw_rank"] and top["vec_rank"] and top["score"] > 0 and out["vector_leg_ok"]
    eid = env.ids["Kernel panics hit the cgroup limit"]
    d = env.http.get(f"/v1/corpus/chunks/{eid}").json()
    assert d["parent"]["text"][d["parent"]["child_start"] : d["parent"]["child_end"]] == d["text"]
    assert env.http.get("/v1/corpus/chunks/missing:1:1").status_code == 404
    nid = env.ids["Named entity recognition uses spaCy"]
    n = env.http.get(f"/v1/corpus/chunks/{nid}/neighbors?k=3").json()
    assert n["items"][0]["near_duplicate"] is True and n["near_dup_threshold"] == 0.2
    assert env.http.get("/v1/corpus/chunks/missing:1:1/neighbors").status_code == 404


def test_concurrent_searches_never_configure_dspy(
    env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """fact-14 / fact-63: no dspy.configure / setup_dspy_router from request workers."""
    from notebooklm._app import assessment

    calls: list[str] = []
    monkeypatch.setattr(dspy, "configure", lambda **kw: calls.append("configure"))
    monkeypatch.setattr(assessment, "setup_dspy_router", lambda: calls.append("router"))
    from concurrent.futures import ThreadPoolExecutor

    def one(i: int) -> int:
        return env.http.post(
            "/v1/corpus/search", json={"query": f"spaCy {i}", "filters": _nb(env)}
        ).status_code

    with ThreadPoolExecutor(6) as pool:
        assert set(pool.map(one, range(12))) == {200}
    assert calls == []
    assert env.embedder.threads  # embedding ran in worker threads without configuring dspy


def test_runs_map_notebooks_health(env: Any) -> None:
    runs = env.http.get(f"/v1/corpus/runs?notebook_id={env.notebook}").json()["items"]
    assert [r["id"] for r in runs] == [env.run_a]
    assert {"strategy", "n_parents", "n_children", "mean_len", "p95_len", "is_active"} <= set(
        runs[0]
    )
    m = env.http.get(f"/v1/corpus/map?notebook_ids={env.notebook}").json()
    assert m["color_by"] == "document" and len(m["points"]) == 3
    assert {"x", "y", "document_id", "external_id"} <= set(m["points"][0])
    nbs = {i["id"]: i for i in env.http.get("/v1/corpus/notebooks").json()["items"]}
    assert nbs[env.notebook]["chunks"] == 3
    health = env.http.get("/v1/corpus/health").json()
    assert health["postgres"]["ok"] is True and health["embedder"]["ok"] is True
    assert health["jobs"] == [] and health["factcheck_runs"] == []


def test_documents_and_document_clauses_routes(env: Any) -> None:
    from notebooklm._app import notebook_titles

    # Store a title in corpus_notebooks to test unsigned-in client
    async def seed_title() -> None:
        async with async_session_maker() as session:
            await notebook_titles.upsert_titles(session, {env.notebook: "Collection Alpha"})

    asyncio.run(seed_title())

    # 1. GET /v1/corpus/documents
    docs_resp = env.http.get(f"/v1/corpus/documents?notebook_ids={env.notebook}")
    assert docs_resp.status_code == 200
    docs = docs_resp.json()["items"]
    assert len(docs) == 1
    doc_a = docs[0]
    assert doc_a["document_id"] == env.doc_a
    assert doc_a["title"] == "Doc A"
    assert doc_a["notebook_id"] == env.notebook
    assert doc_a["collection_id"] == env.notebook
    assert doc_a["collection_title"] == "Collection Alpha"
    assert doc_a["clause_count"] == 3
    assert doc_a["tagged_count"] == 0
    assert doc_a["fact_checked_count"] == 0
    assert "file_type" in doc_a

    # 2. GET /v1/corpus/documents/{document_id}/clauses
    clauses_resp = env.http.get(f"/v1/corpus/documents/{env.doc_a}/clauses")
    assert clauses_resp.status_code == 200
    data = clauses_resp.json()
    assert data["document_id"] == env.doc_a
    assert data["title"] == "Doc A"
    assert data["collection_title"] == "Collection Alpha"
    assert len(data["chunks"]) == 2  # 2 parent chunks in doc A
    chunk0 = data["chunks"][0]
    assert "clauses" in chunk0
    assert chunk0["clause_count"] == 2
    assert chunk0["clauses"][0]["text"] == "Named entity recognition uses spaCy"

    # 3. GET /v1/corpus/documents/missing/clauses -> 404
    missing_resp = env.http.get("/v1/corpus/documents/missing-doc-id/clauses")
    assert missing_resp.status_code == 404
    assert missing_resp.json()["error"]["category"] == "not_found"


def test_notebook_titles_stored_live_and_failure(env: Any) -> None:
    """Stored titles show without a client, a live list refreshes them, a live failure keeps them."""
    from notebooklm._app import notebook_titles

    def seed_stored() -> None:
        async def go() -> None:
            async with async_session_maker() as session:
                await notebook_titles.upsert_titles(session, {env.notebook: "Stored Title"})

        asyncio.run(go())

    def stored() -> str | None:
        async def go() -> str | None:
            async with async_session_maker() as session:
                titles = await notebook_titles.stored_titles(session, [env.notebook])
                return titles.get(env.notebook)

        return asyncio.run(go())

    seed_stored()
    assert stored() == "Stored Title"

    class LiveList:
        async def list(self) -> list[Any]:
            return [type("Nb", (), {"id": env.notebook, "title": "Live Title"})()]

    class DeadList:
        async def list(self) -> list[Any]:
            raise RuntimeError("signed out")

    env.client.notebooks = LiveList()  # type: ignore[attr-defined]
    items = {i["id"]: i["title"] for i in env.http.get("/v1/corpus/notebooks").json()["items"]}
    assert items[env.notebook] == "Live Title"  # the live list overlays the stored row
    assert stored() == "Live Title"  # ...and is persisted

    env.client.notebooks = DeadList()  # type: ignore[attr-defined]
    items = {i["id"]: i["title"] for i in env.http.get("/v1/corpus/notebooks").json()["items"]}
    assert items[env.notebook] == "Live Title"  # a live failure keeps the stored title

    env.client.notebooks = FakeNotebooks()  # type: ignore[attr-defined]
    services = CorpusServices(session_maker=async_session_maker, configure_llm=False)
    no_client = create_app(corpus_services=services, client_factory=_never)
    with TestClient(no_client, headers=HEADERS, client=("127.0.0.1", 5555)) as http:
        items = {i["id"]: i["title"] for i in http.get("/v1/corpus/notebooks").json()["items"]}
        assert items[env.notebook] == "Live Title"  # no client at all → stored title only


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------


def test_delete_preview_then_confirm(env: Any) -> None:
    eid = env.ids["The OOM killer picks the largest RSS"]
    preview = env.http.post(
        "/v1/corpus/delete/preview", json={"level": "clause", "ids": [eid]}
    ).json()
    assert preview["counts"]["clauses"] == 1 and preview["counts"]["embeddings"] == 1
    assert env.http.get(f"/v1/corpus/chunks/{eid}").status_code == 200  # preview deletes nothing
    receipt = env.http.post(
        "/v1/corpus/delete", json={"level": "clause", "ids": [eid], "reason": "redundant"}
    ).json()
    assert receipt["counts"]["clauses"] == 1 and len(receipt["removal_log_ids"]) == 1
    assert env.http.get(f"/v1/corpus/chunks/{eid}").status_code == 404
    bad = env.http.post("/v1/corpus/delete", json={"level": "run", "ids": ["x"]})
    assert bad.status_code == 422
    bad_reason = env.http.post(
        "/v1/corpus/delete/preview", json={"level": "clause", "ids": ["x"], "reason": "?"}
    )
    assert bad_reason.status_code == 422


def test_delete_refused_while_ingesting(env: Any) -> None:
    async def hold(job: Any) -> None:
        await asyncio.sleep(5)

    async def start() -> None:
        env.services.jobs.start("ingest", "x", hold, document_ids={env.doc_a})

    env.http.portal.call(start)  # type: ignore[attr-defined]
    resp = env.http.post(
        "/v1/corpus/delete", json={"level": "document", "ids": [env.doc_a], "reason": "other"}
    )
    assert resp.status_code == 409 and resp.json()["error"]["category"] == "busy"


def test_export_and_note(env: Any) -> None:
    ids = [env.ids["Named entity recognition uses spaCy"]]
    md = env.http.post("/v1/corpus/export", json={"ids": ids, "format": "markdown"})
    assert md.headers["content-type"].startswith("text/markdown")
    assert "attachment" in md.headers["content-disposition"] and "> Named entity" in md.text
    js = env.http.post("/v1/corpus/export", json={"ids": ids, "format": "json"})
    assert json.loads(js.text)["chunks"][0]["external_id"] == ids[0]
    note = env.http.post("/v1/corpus/export/note", json={"ids": ids}).json()
    assert note["notes"] == [{"notebook_id": env.notebook, "note_id": "note-1", "count": 1}]
    assert env.http.post("/v1/corpus/export/note", json={"ids": ["missing"]}).status_code == 422


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------


def test_answer_notebooklm_scoped_with_citations(env: Any) -> None:
    out = env.http.post(
        "/v1/corpus/answer",
        json={
            "question": "kernel panics",
            "mode": "notebooklm",
            "filters": {"notebook_ids": [env.notebook]},
        },
    ).json()
    call = env.client.chat.calls[0]
    assert call["nb"] == env.notebook and call["source_ids"] == [env.doc_a]
    assert "[C1]" in call["q"] and out["citations"]["C1"] == out["hits"][0]["external_id"]


def test_answer_auto_picks_agent_across_notebooks(env: Any) -> None:
    ids = [
        env.ids["Named entity recognition uses spaCy"],
        env.ids["Entity recognition with spaCy pipelines"],
    ]
    out = env.http.post("/v1/corpus/answer", json={"question": "spaCy?", "ids": ids}).json()
    assert out["mode"] == "corpus_agent" and out["answer"] == "merged [C1] [C2]"
    assert out["citations"] == {"C1": ids[0], "C2": ids[1]}
    assert len(out["per_notebook"]) == 2


def test_answer_model_streams_over_sse(env: Any) -> None:
    events = _sse(
        env.http,
        "/v1/corpus/answer",
        until="done",
        method="POST",
        json={"question": "spaCy?", "mode": "model", "model": "openrouter/x", "filters": _nb(env)},
    )
    assert [e["type"] for e in events] == ["hits", "token", "token", "done"]
    assert events[-1]["answer"] == "SpaCy [C1]" and "C1" in events[-1]["citations"]
    assert (
        env.http.post(
            "/v1/corpus/answer", json={"question": "q", "mode": "model", "filters": _nb(env)}
        ).status_code
        == 422
    )


def test_answer_deep_unavailable_and_no_hits(env: Any) -> None:
    resp = env.http.post(
        "/v1/corpus/answer", json={"question": "spaCy", "mode": "deep", "filters": _nb(env)}
    )
    assert resp.status_code == 409 and resp.json()["error"]["category"] == "deep_mode_unavailable"
    none = env.http.post(
        "/v1/corpus/answer",
        json={"question": "zzzz", "mode": "notebooklm", "filters": {"notebook_ids": ["nope"]}},
    )
    assert none.status_code == 404


# ---------------------------------------------------------------------------
# Artifacts, providers, SFL, jobs
# ---------------------------------------------------------------------------


def test_providers_with_key_status(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPEECHMATICS_API_KEY", raising=False)
    monkeypatch.setenv("DEEPGRAM_API_KEY", "x")
    monkeypatch.setenv("NOTEBOOKLM_TRANSCRIBE_PROVIDER", "deepgram")
    out = env.http.get("/v1/corpus/transcription/providers").json()
    by_id = {p["id"]: p for p in out["providers"]}
    assert (
        by_id["deepgram"]["key_present"] is True and by_id["speechmatics"]["key_present"] is False
    )
    assert out["defaults"]["provider"] == "deepgram" and out["defaults"]["language"] == "auto"


def test_artifact_list_and_ingest_job(env: Any) -> None:
    items = env.http.get(f"/v1/corpus/artifacts?notebook_id={env.notebook}").json()["items"]
    assert {i["kind"]: i["ingestible"] for i in items} == {"report": True, "infographic": False}
    aid = f"{env.prefix}-report"
    job = env.http.post(f"/v1/corpus/artifacts/{aid}/ingest", json={"notebook_id": env.notebook})
    assert job.status_code == 202
    job_id = job.json()["id"]
    events = _sse(env.http, f"/v1/corpus/jobs/{job_id}/events", until="finished")
    assert events[-1]["status"] == "done" and events[-1]["result"]["status"] == "ingested"
    replay = _sse(env.http, f"/v1/corpus/jobs/{job_id}/events?after=1", until="finished")
    assert replay[0]["seq"] == 2
    again = env.http.post(
        f"/v1/corpus/artifacts/{aid}/ingest", json={"notebook_id": env.notebook}
    ).json()
    _wait(lambda: env.http.get(f"/v1/corpus/jobs/{again['id']}").json()["status"] == "done")
    assert (
        env.http.get(f"/v1/corpus/jobs/{again['id']}").json()["result"]["status"]
        == "skipped_unchanged"
    )
    assert len(env.http.get("/v1/corpus/jobs").json()["items"]) == 2
    assert env.http.get("/v1/corpus/jobs/nope").status_code == 404
    assert env.http.get("/v1/corpus/jobs/nope/events").status_code == 404


def test_ingest_writes_notebook_title(env: Any) -> None:
    """Starting an ingest stores the notebook's live title in Postgres (fact 1, ingest path)."""
    from notebooklm._app import notebook_titles

    def stored() -> str | None:
        async def go() -> str | None:
            async with async_session_maker() as session:
                titles = await notebook_titles.stored_titles(session, [env.notebook])
                return titles.get(env.notebook)

        return asyncio.run(go())

    class LiveList:
        async def list(self) -> list[Any]:
            return [type("Nb", (), {"id": env.notebook, "title": "Ingested Title"})()]

    assert stored() is None  # the seeded notebook has no stored title yet
    env.client.notebooks = LiveList()  # type: ignore[attr-defined]
    aid = f"{env.prefix}-report"
    job = env.http.post(f"/v1/corpus/artifacts/{aid}/ingest", json={"notebook_id": env.notebook})
    assert job.status_code == 202
    assert stored() == "Ingested Title"  # written by the ingest request itself
    job_id = job.json()["id"]
    _wait(lambda: env.http.get(f"/v1/corpus/jobs/{job_id}").json()["status"] == "done")


def test_sfl_run_for_document_scope(
    env: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    from notebooklm._app import tracing

    caplog.set_level(logging.INFO, logger="notebooklm._app.background")
    caplog.set_level(logging.INFO, logger="notebooklm.server.routes.corpus")
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing.trace, "get_tracer", provider.get_tracer)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)

    job = env.http.post("/v1/corpus/sfl/runs", json={"scope": {"document_ids": [env.doc_b]}}).json()
    assert job["trace_url"] is None  # the snapshot predates the root span closing
    events = _sse(env.http, f"/v1/corpus/jobs/{job['id']}/events", until="finished")
    assert events[0]["type"] == "started" and events[-1]["status"] == "done"
    assert events[-1]["result"] == {"tagged": 2, "failed": 0}
    clauses = [e for e in events if str(e.get("message", "")).startswith("tagging clause")]
    assert [(e["message"], e["done"], e["total"]) for e in clauses] == [
        ("tagging clause 1/2", 0, 2),
        ("tagging clause 2/2", 1, 2),
        ("tagging clause 2/2", 1, 2),
        ("tagging clause 2/2", 2, 2),
    ]

    # fact 16/18: one job.sfl_tag root span; the snapshot links to its Langfuse trace.
    roots = [s for s in exporter.get_finished_spans() if s.name == "job.sfl_tag"]
    assert len(roots) == 1
    trace_hex = format(roots[0].context.trace_id, "032x")
    done = env.http.get(f"/v1/corpus/jobs/{job['id']}").json()
    assert done["trace_url"] == f"http://tinybot:3000/trace/{trace_hex}"

    # fact 17: INFO lines at start, per parent and finish, each with the job id.
    lines = [r.message for r in caplog.records if f"job_id={job['id']}" in r.message]
    assert any("started" in m for m in lines)
    assert any("parent 1/1 tagged=2 failed=0" in m for m in lines)
    assert any("kind=sfl_tag done" in m for m in lines)

    a = env.http.get(f"/v1/corpus/chunks/{env.ids['Kernel panics hit the cgroup limit']}").json()
    b = env.http.get(f"/v1/corpus/chunks/{env.ids['It might rain']}").json()
    assert a["has_sfl"] is False and b["has_sfl"] is True
    assert env.http.post("/v1/corpus/sfl/runs", json={"scope": {}}).status_code == 422

    # failing variant: ERROR line with the job id
    empty = env.http.post("/v1/corpus/sfl/runs", json={"scope": {"document_ids": ["nope"]}}).json()
    _wait(lambda: env.http.get(f"/v1/corpus/jobs/{empty['id']}").json()["status"] == "failed")
    errors = [r for r in caplog.records if f"job_id={empty['id']}" in r.message and r.levelno >= 40]
    assert errors and "no ingested children in scope" in errors[0].message


def test_corpus_explorer_module_is_llm_free() -> None:
    """The search/browse layer imports no DSPy at all (fact-14)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(corpus_explorer))
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "dspy" not in imported and "setup_dspy_router" not in imported


def test_llm_configured_only_on_main_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """fact-63: the server configures DSPy once, on the main thread, never in workers."""
    from notebooklm._app import assessment
    from notebooklm.server import _corpus

    calls: list[str] = []
    monkeypatch.setattr(
        assessment, "setup_dspy_router", lambda: calls.append(threading.current_thread().name)
    )
    assert _corpus.configure_llm_on_main_thread(CorpusServices()) is (
        threading.current_thread() is threading.main_thread()
    )
    result: dict[str, bool] = {}
    worker = threading.Thread(
        target=lambda: result.update(ok=_corpus.configure_llm_on_main_thread(CorpusServices()))
    )
    worker.start()
    worker.join()
    assert result == {"ok": False}
    assert _corpus.configure_llm_on_main_thread(CorpusServices(configure_llm=False)) is False
    assert all(name == threading.main_thread().name for name in calls)

    def boom() -> None:
        raise RuntimeError("no key")

    monkeypatch.setattr(assessment, "setup_dspy_router", boom)
    if threading.current_thread() is threading.main_thread():
        assert _corpus.configure_llm_on_main_thread(CorpusServices()) is False


def test_sse_keepalive(monkeypatch: pytest.MonkeyPatch) -> None:
    from notebooklm.server import _corpus

    monkeypatch.setattr(_corpus, "SSE_KEEPALIVE", 0.01)

    async def slow() -> Any:
        await asyncio.sleep(0.05)
        yield {"type": "x", "seq": 1}

    async def collect() -> list[str]:
        resp = _corpus.sse_response(slow())
        return [chunk async for chunk in resp.body_iterator]  # type: ignore[union-attr]

    chunks = asyncio.run(collect())
    assert chunks[0] == ": keep-alive\n\n"
    assert chunks[-1].startswith("id: 1\nevent: x\ndata: ")
