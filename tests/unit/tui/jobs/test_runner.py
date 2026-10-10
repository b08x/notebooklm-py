from __future__ import annotations

import asyncio
import threading
import time

from notebooklm.tui.jobs.runner import JobContext, JobRunner, worker_count
from notebooklm.tui.jobs.store import ItemStatus, JobStatus, JobStore


def _wait_for(pred, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_worker_count_env(monkeypatch) -> None:
    monkeypatch.delenv("NOTEBOOKLM_TUI_JOB_WORKERS", raising=False)
    assert worker_count() == 2
    monkeypatch.setenv("NOTEBOOKLM_TUI_JOB_WORKERS", "5")
    assert worker_count() == 5


def test_success_stores_summary_and_items(store: JobStore) -> None:
    async def handle(ctx: JobContext) -> str:
        item = ctx.add_item("a.mp3", "artifact")
        ctx.phase("downloading", 50)
        ctx.item_done(item, bytes=10)
        return "1 asset"

    job_id = store.enqueue("download", "nb")
    job = store.claim()
    JobRunner(store, {"download": handle}).run_job(job)  # type: ignore[arg-type]
    done = store.get(job_id)
    assert done is not None
    assert (done.status, done.summary, done.percent) == (JobStatus.DONE, "1 asset", 100.0)
    assert store.items(job_id)[0].status == ItemStatus.DONE


def test_exception_fails_job_with_message(store: JobStore) -> None:
    async def handle(ctx: JobContext) -> None:
        raise ValueError("bad notebook")

    job_id = store.enqueue("ingest", "nb")
    JobRunner(store, {"ingest": handle}).run_job(store.claim())  # type: ignore[arg-type]
    job = store.get(job_id)
    assert job is not None and job.status == JobStatus.FAILED
    assert job.error == "ValueError: bad notebook"


def test_unknown_kind_fails(store: JobStore) -> None:
    job_id = store.enqueue("nope")
    JobRunner(store, {}).run_job(store.claim())  # type: ignore[arg-type]
    assert store.get(job_id).status == JobStatus.FAILED  # type: ignore[union-attr]


def test_cancel_running_stops_at_next_check(store: JobStore) -> None:
    started = threading.Event()
    processed: list[int] = []

    async def handle(ctx: JobContext) -> str:
        for i in range(100):
            ctx.check_cancelled()
            processed.append(i)
            started.set()
            await asyncio.sleep(0.02)
        return "finished"

    job_id = store.enqueue("download", "nb")
    runner = JobRunner(store, {"download": handle}, workers=1, poll_interval=0.01)
    runner.start()
    try:
        assert started.wait(5)
        store.request_cancel(job_id)
        _wait_for(lambda: store.get(job_id).status == JobStatus.CANCELLED)  # type: ignore[union-attr]
    finally:
        runner.stop()
    assert len(processed) < 100


def test_at_most_n_jobs_run_concurrently(store: JobStore) -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    async def handle(ctx: JobContext) -> None:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        await asyncio.sleep(0.15)
        with lock:
            active -= 1

    ids = [store.enqueue("download", f"nb{i}") for i in range(6)]
    runner = JobRunner(store, {"download": handle}, workers=2, poll_interval=0.01)
    runner.start()
    try:
        _wait_for(lambda: all(store.get(i).status == JobStatus.DONE for i in ids))  # type: ignore[union-attr]
    finally:
        runner.stop()
    assert peak == 2


def test_acquire_token_waits_on_shared_bucket(store: JobStore) -> None:
    calls = {"n": 0}

    def consume() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    async def handle(ctx: JobContext) -> None:
        await ctx.acquire_token()

    store.enqueue("download", "nb")
    job = store.claim()
    runner = JobRunner(store, {"download": handle}, consume_token=consume)
    runner.run_job(job)  # type: ignore[arg-type]
    assert calls["n"] == 3


def test_handler_runs_with_bound_lm(store: JobStore) -> None:
    import dspy

    sentinel = dspy.LM("openai/test-model", api_key="x")
    seen = {}

    async def handle(ctx: JobContext) -> None:
        seen["lm"] = dspy.settings.lm

    store.enqueue("sfl_tag", "nb")
    job = store.claim()
    result: dict[str, object] = {}

    def in_worker() -> None:
        JobRunner(store, {"sfl_tag": handle}, lm=sentinel).run_job(job)  # type: ignore[arg-type]
        result["ok"] = True

    t = threading.Thread(target=in_worker)
    t.start()
    t.join(5)
    assert result.get("ok") and seen["lm"] is sentinel
