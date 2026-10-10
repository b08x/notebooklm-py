from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from notebooklm.tui.jobs.handlers.ingest import run_ingest
from notebooklm.tui.jobs.runner import JobContext
from notebooklm.tui.jobs.store import ItemStatus, JobStore
from notebooklm.tui.state import TUIState
from notebooklm.tui.views.notebook_detail import start_ingestion


class _Client:
    def __init__(self, sources: list[Any], notes: list[Any]) -> None:
        self.sources = SimpleNamespace(list=self._list(sources))
        self.notes = SimpleNamespace(list=self._list(notes))

    @staticmethod
    def _list(items):
        async def _f(_nb):
            return items

        return _f

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Service:
    def __init__(self, counts: dict[str, Any]) -> None:
        self.counts = counts
        self.calls: list[tuple[str, str]] = []

    def _count(self, doc_id: str) -> int:
        value = self.counts[doc_id]
        if isinstance(value, Exception):
            raise value
        return value

    async def ingest_source(self, session, notebook_id, source_id, *, context=None):
        self.calls.append(("source", source_id))
        return self._count(source_id)

    async def ingest_text(self, session, *, document_id, text, notebook_id, context):
        self.calls.append(("note", document_id))
        return self._count(document_id)


def _ctx(store: JobStore, payload: dict[str, Any]) -> JobContext:
    store.enqueue("ingest", "nb-1", payload)
    job = store.claim()
    assert job is not None
    return JobContext(job, store)


async def _run(store, payload, client, service, strategies):
    return await run_ingest(
        _ctx(store, payload),
        client_factory=lambda: client,
        session_factory=_Session,
        service_factory=lambda c, s: service,
        strategy_factory=lambda name, params: strategies.append((name, params)) or name,
    )


@pytest.mark.asyncio
async def test_sums_children_and_records_failures(store: JobStore) -> None:
    client = _Client([SimpleNamespace(id="s1", title="One"), SimpleNamespace(id="s2")], [])
    service = _Service({"s1": RuntimeError("boom"), "s2": 4})
    strategies: list = []
    summary = await _run(store, {}, client, service, strategies)
    assert summary == "Ingested 4 children from 2 documents (recursive); 1 failed"
    assert strategies == [("recursive", {})]
    job_id = store.list_jobs()[0].id
    items = {i.name: i for i in store.items(job_id)}
    assert items["One"].status == ItemStatus.FAILED and "boom" in (items["One"].error or "")
    assert items["s2"].status == ItemStatus.DONE


@pytest.mark.asyncio
async def test_filters_by_selected_ids_and_ingests_notes(store: JobStore) -> None:
    client = _Client(
        [SimpleNamespace(id="s1"), SimpleNamespace(id="s2")],
        [SimpleNamespace(id="n1", title="Note", content="Body."), SimpleNamespace(id="n2")],
    )
    service = _Service({"s2": 2, "n1": 1})
    strategies: list = []
    payload = {
        "strategy": "cluster_semantic",
        "params": {"percentile": 80},
        "source_ids": ["s2", "n1"],
    }
    summary = await _run(store, payload, client, service, strategies)
    assert service.calls == [("source", "s2"), ("note", "n1")]
    assert strategies == [("cluster_semantic", {"percentile": 80})]
    assert summary.startswith("Ingested 3 children from 2 documents")


@pytest.mark.asyncio
async def test_zero_children_marks_item_skipped(store: JobStore) -> None:
    client = _Client([SimpleNamespace(id="s1")], [])
    await _run(store, {}, client, _Service({"s1": 0}), [])
    item = store.items(store.list_jobs()[0].id)[0]
    assert item.status == ItemStatus.SKIPPED


def test_start_ingestion_enqueues_job(store: JobStore) -> None:
    state = TUIState()
    state.selected_notebook = "nb-9"
    state.job_store = store
    state.context_overrides["nb-9"] = "ctx"
    start_ingestion(state, {"b", "a"}, strategy="dynamic_window")
    (job,) = store.list_jobs()
    assert (job.kind, job.notebook_id) == ("ingest", "nb-9")
    assert job.payload == {
        "strategy": "dynamic_window",
        "params": {},
        "source_ids": ["a", "b"],
        "context": "ctx",
    }
