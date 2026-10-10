"""``topic_model`` handler tests with injected loader, fit, saver and session fakes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any

import pytest

from notebooklm.tui.jobs.handlers.topic_model import run_topic_model
from notebooklm.tui.jobs.runner import JobContext
from notebooklm.tui.jobs.store import ItemStatus, Job, JobStatus


class _FakeStore:
    """The subset of ``JobStore`` that ``JobContext`` uses, kept in memory."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.fields: dict[str, Any] = {}
        self._n = 0

    def add_item(self, job_id: str, name: str, kind: str = "") -> str:
        self._n += 1
        item_id = f"i{self._n}"
        self.items[item_id] = {"name": name, "kind": kind, "status": ItemStatus.PENDING}
        return item_id

    def update_item(self, job_id: str, item_id: str, **fields: Any) -> None:
        self.items[item_id].update(fields)

    def update(self, job_id: str, **fields: Any) -> None:
        self.fields.update(fields)

    def is_cancel_requested(self, job_id: str) -> bool:
        return False


def _ctx(store: _FakeStore, payload: dict[str, Any] | None = None) -> JobContext:
    job = Job(
        id="job-1",
        kind="topic_model",
        status=JobStatus.RUNNING,
        payload=payload or {},
    )
    return JobContext(job, store)  # type: ignore[arg-type]


@asynccontextmanager
async def _session():
    yield object()


def _loader(ids: list[str], texts: list[str], vectors: list[list[float]]):
    async def load(session: Any):
        return ids, texts, vectors

    return load


def test_handler_runs_all_items_and_saves_matching_lengths() -> None:
    store = _FakeStore()
    fit_calls: list[dict[str, Any]] = []
    save_calls: list[dict[str, Any]] = []

    def fit(docs, vectors, *, min_topic_size):
        fit_calls.append({"n": len(docs), "min_topic_size": min_topic_size})
        numbers = [0, 0, 1, -1]
        topics = [
            {"topic_number": -1, "label": "-1_x", "keywords": ["x"], "size": 1},
            {"topic_number": 0, "label": "0_a", "keywords": ["a"], "size": 2},
            {"topic_number": 1, "label": "1_b", "keywords": ["b"], "size": 1},
        ]
        return numbers, topics

    async def save(session, params, trace_id, topic_numbers, topics, clause_ids):
        save_calls.append(
            {
                "params": params,
                "trace_id": trace_id,
                "n_numbers": len(topic_numbers),
                "n_ids": len(clause_ids),
            }
        )
        return 7

    summary = asyncio.run(
        run_topic_model(
            _ctx(store, {"min_topic_size": 5}),
            session_factory=_session,
            load=_loader(["c0", "c1", "c2", "c3"], ["t0", "t1", "t2", "t3"], [[0.0]] * 4),
            fit=fit,
            save=save,
        )
    )

    assert summary == "2 topics over 4 children"
    assert fit_calls == [{"n": 4, "min_topic_size": 5}]
    assert save_calls == [
        {"params": {"min_topic_size": 5}, "trace_id": None, "n_numbers": 4, "n_ids": 4}
    ]
    assert [item["status"] for item in store.items.values()] == [ItemStatus.DONE] * 3
    assert [item["kind"] for item in store.items.values()] == ["load", "fit", "write"]


def test_handler_defaults_min_topic_size_to_ten() -> None:
    store = _FakeStore()
    seen: list[int] = []

    def fit(docs, vectors, *, min_topic_size):
        seen.append(min_topic_size)
        return [0], [{"topic_number": 0, "label": "0_a", "keywords": [], "size": 1}]

    async def save(*args, **kwargs):
        return 1

    asyncio.run(
        run_topic_model(
            _ctx(store),
            session_factory=_session,
            load=_loader(["c0"], ["t0"], [[0.0]]),
            fit=fit,
            save=save,
        )
    )

    assert seen == [10]


def test_empty_corpus_raises_and_skips_fit() -> None:
    store = _FakeStore()
    fit_calls: list[Any] = []

    def fit(docs, vectors, *, min_topic_size):
        fit_calls.append(docs)
        return [], []

    async def save(*args, **kwargs):
        raise AssertionError("save must not run")

    with pytest.raises(RuntimeError, match="no ingested children; run ingest first"):
        asyncio.run(
            run_topic_model(
                _ctx(store),
                session_factory=_session,
                load=_loader([], [], []),
                fit=fit,
                save=save,
            )
        )

    assert fit_calls == []
    assert [item["status"] for item in store.items.values()] == [ItemStatus.FAILED]
