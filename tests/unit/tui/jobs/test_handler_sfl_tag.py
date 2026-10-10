from __future__ import annotations

import asyncio
from typing import Any

import dspy
import pytest

from notebooklm.tui.jobs.handlers.sfl_tag import ChildRow, run_sfl_tag, to_sfl
from notebooklm.tui.jobs.runner import JobCancelled, JobContext
from notebooklm.tui.jobs.store import ItemStatus, JobStore

OUTPUT = {
    "ideational": {"participants": ["the cat"], "processes": ["sit"], "circumstances": []},
    "interpersonal": {"mood": "declarative", "modality": "high", "tenor": "formal"},
}


class FakeEngine:
    def __init__(self, fail_on: set[str] | None = None, cancel_store: tuple | None = None):
        self.fail_on = fail_on or set()
        self.cancel_store = cancel_store
        self.calls: list[str] = []
        self.lms: list[Any] = []

    def forward(self, text: str) -> dict[str, Any]:
        self.calls.append(text)
        self.lms.append(dspy.settings.lm)
        if self.cancel_store is not None:
            store, job_id = self.cancel_store
            store.request_cancel(job_id)
        if text in self.fail_on:
            raise ValueError(f"bad input: {text}")
        return OUTPUT


class FakeDb:
    """Stands in for the Postgres load/save functions."""

    def __init__(self, children: list[ChildRow]) -> None:
        self.children = children
        self.saved: list[dict[int, dict[str, Any]]] = []

    async def load(self, session_factory: Any, notebook_id: Any) -> list[ChildRow]:
        return self.children

    async def save(self, session_factory: Any, values: dict[int, dict[str, Any]]) -> None:
        self.saved.append(values)


def _children() -> list[ChildRow]:
    return [
        ChildRow(id=1, parent_id=10, parent_index=0, text="The cat sat."),
        ChildRow(id=2, parent_id=10, parent_index=0, text="It was warm."),
        ChildRow(id=3, parent_id=11, parent_index=1, text="Dogs bark."),
    ]


def _ctx(store: JobStore) -> tuple[JobContext, str]:
    job_id = store.enqueue("sfl_tag", notebook_id="nb1")
    job = store.claim()
    assert job is not None
    return JobContext(job, store), job_id


def _saved_ids(db: FakeDb) -> set[int]:
    return {cid for batch in db.saved for cid in batch}


def test_every_child_gets_sfl_mood_modality_tenor(store: JobStore) -> None:
    ctx, _ = _ctx(store)
    db = FakeDb(_children())
    engine = FakeEngine()

    summary = asyncio.run(
        run_sfl_tag(ctx, load=db.load, save=db.save, engine_factory=lambda: engine)
    )

    assert summary == "Tagged 3 children (0 failed)"
    assert _saved_ids(db) == {1, 2, 3}
    for batch in db.saved:
        for sfl in batch.values():
            assert sfl["mood"] == "declarative"
            assert sfl["modality"] == "high"
            assert sfl["tenor"] == "formal"
            assert sfl["pass1"] == OUTPUT["ideational"]
            assert "raw" not in sfl


def test_to_sfl_keeps_extra_keys_under_raw() -> None:
    output = {
        "ideational": {"participants": []},
        "interpersonal": {"mood": "interrogative", "error": "parse failed"},
        "extra": 1,
    }
    sfl = to_sfl(output)
    assert sfl["mood"] == "interrogative"
    assert sfl["modality"] is None
    assert sfl["tenor"] is None
    assert sfl["raw"] == {"error": "parse failed", "extra": 1}


def test_engine_runs_under_the_bound_lm(store: JobStore) -> None:
    ctx, _ = _ctx(store)
    db = FakeDb(_children())
    engine = FakeEngine()
    lm = object()

    with dspy.context(lm=lm):
        asyncio.run(run_sfl_tag(ctx, load=db.load, save=db.save, engine_factory=lambda: engine))

    assert len(engine.lms) == 3
    assert all(seen is lm for seen in engine.lms)


def test_one_item_per_parent_and_commit_per_parent(store: JobStore) -> None:
    ctx, job_id = _ctx(store)
    db = FakeDb(_children())

    asyncio.run(run_sfl_tag(ctx, load=db.load, save=db.save, engine_factory=lambda: FakeEngine()))

    items = store.items(job_id)
    assert [i.name for i in items] == ["parent 0: 2 children", "parent 1: 1 children"]
    assert all(i.status == ItemStatus.DONE for i in items)
    assert [sorted(batch) for batch in db.saved] == [[1, 2], [3]]


def test_raising_child_fails_its_parent_item_and_others_are_saved(store: JobStore) -> None:
    ctx, job_id = _ctx(store)
    db = FakeDb(_children())
    engine = FakeEngine(fail_on={"It was warm."})

    summary = asyncio.run(
        run_sfl_tag(ctx, load=db.load, save=db.save, engine_factory=lambda: engine)
    )

    assert summary == "Tagged 2 children (1 failed)"
    assert _saved_ids(db) == {1, 3}
    items = store.items(job_id)
    assert items[0].status == ItemStatus.FAILED
    assert "bad input: It was warm." in (items[0].error or "")
    assert items[1].status == ItemStatus.DONE


def test_no_active_children_raises(store: JobStore) -> None:
    ctx, _ = _ctx(store)
    db = FakeDb([])

    with pytest.raises(RuntimeError, match="no ingested children; run ingest first"):
        asyncio.run(
            run_sfl_tag(ctx, load=db.load, save=db.save, engine_factory=lambda: FakeEngine())
        )
    assert db.saved == []


def test_cancel_stops_before_next_child_and_keeps_finished_work(store: JobStore) -> None:
    ctx, job_id = _ctx(store)
    db = FakeDb(_children())
    engine = FakeEngine(cancel_store=(store, job_id))

    with pytest.raises(JobCancelled):
        asyncio.run(run_sfl_tag(ctx, load=db.load, save=db.save, engine_factory=lambda: engine))

    assert engine.calls == ["The cat sat."]
    assert _saved_ids(db) == {1}
