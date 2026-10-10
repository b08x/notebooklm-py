from __future__ import annotations

import pytest

from notebooklm.tui.jobs.store import FINISHED_TTL_SECONDS, ItemStatus, JobStatus, JobStore


def test_enqueue_creates_hash_with_fields(store: JobStore) -> None:
    job_id = store.enqueue("download", "nb1", {"x": 1})
    job = store.get(job_id)
    assert job is not None
    assert (job.kind, job.notebook_id, job.status, job.payload) == (
        "download",
        "nb1",
        JobStatus.QUEUED,
        {"x": 1},
    )
    raw = store.r.hgetall(store.job_key(job_id))
    for key in ("id", "kind", "status", "notebook_id", "phase", "percent", "created_at"):
        assert key in raw


def test_three_enqueues_list_three_jobs_newest_first(store: JobStore) -> None:
    ids = [store.enqueue("download", f"nb{i}") for i in range(3)]
    assert [j.id for j in store.list_jobs()] == list(reversed(ids))


def test_claim_is_fifo_and_marks_running(store: JobStore) -> None:
    first = store.enqueue("download", "a")
    store.enqueue("download", "b")
    job = store.claim()
    assert job is not None and job.id == first
    assert job.status == JobStatus.RUNNING and job.started_at is not None


def test_claim_empty_returns_none(store: JobStore) -> None:
    assert store.claim() is None


def test_mark_interrupted_on_startup(store: JobStore) -> None:
    store.enqueue("ingest", "a")
    running = store.claim()
    assert running is not None
    queued = store.enqueue("ingest", "b")
    assert store.mark_interrupted_on_startup() == 1
    assert store.get(running.id).status == JobStatus.INTERRUPTED  # type: ignore[union-attr]
    assert store.get(queued).status == JobStatus.QUEUED  # type: ignore[union-attr]


def test_cancel_queued_removes_from_queue(store: JobStore) -> None:
    job_id = store.enqueue("download", "a")
    store.request_cancel(job_id)
    assert store.get(job_id).status == JobStatus.CANCELLED  # type: ignore[union-attr]
    assert store.claim() is None


def test_cancel_running_sets_flag(store: JobStore) -> None:
    store.enqueue("download", "a")
    job = store.claim()
    assert job is not None
    store.request_cancel(job.id)
    assert store.is_cancel_requested(job.id)
    assert store.get(job.id).status == JobStatus.RUNNING  # type: ignore[union-attr]


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.CANCELLED])
def test_retry_requeues_and_clears_items(store: JobStore, status: JobStatus) -> None:
    store.enqueue("download", "a")
    job = store.claim()
    assert job is not None
    store.add_item(job.id, "src1")
    store.finish(job.id, status, error="boom")
    assert store.retry(job.id)
    again = store.get(job.id)
    assert again is not None and again.status == JobStatus.QUEUED and again.error is None
    assert store.items(job.id) == []
    assert store.r.ttl(store.job_key(job.id)) == -1
    assert store.claim().id == job.id  # type: ignore[union-attr]


def test_retry_refuses_done_job(store: JobStore) -> None:
    store.enqueue("download", "a")
    job = store.claim()
    store.finish(job.id, JobStatus.DONE)  # type: ignore[union-attr]
    assert not store.retry(job.id)  # type: ignore[union-attr]


def test_finish_sets_seven_day_ttl_on_job_and_items(store: JobStore) -> None:
    store.enqueue("download", "a")
    job = store.claim()
    assert job is not None
    item = store.add_item(job.id, "art1", "artifact")
    store.finish(job.id, JobStatus.DONE, summary="ok")
    for key in (store.job_key(job.id), store.items_key(job.id), store.item_key(job.id, item)):
        ttl = store.r.ttl(key)
        assert FINISHED_TTL_SECONDS - 60 < ttl <= FINISHED_TTL_SECONDS


def test_items_record_failure_text(store: JobStore) -> None:
    job_id = store.enqueue("download", "a")
    ok = store.add_item(job_id, "good.mp3", "artifact")
    bad = store.add_item(job_id, "bad.mp4", "artifact")
    store.update_item(job_id, ok, status=ItemStatus.DONE, bytes=1234)
    store.update_item(job_id, bad, status=ItemStatus.FAILED, error="HTTP 403")
    items = store.items(job_id)
    assert [(i.name, i.status, i.bytes, i.error) for i in items] == [
        ("good.mp3", ItemStatus.DONE, 1234, None),
        ("bad.mp4", ItemStatus.FAILED, None, "HTTP 403"),
    ]


def test_clear_finished_keeps_active(store: JobStore) -> None:
    done = store.enqueue("download", "a")
    store.claim()
    store.finish(done, JobStatus.DONE)
    queued = store.enqueue("download", "b")
    assert store.clear_finished() == 1
    assert [j.id for j in store.list_jobs()] == [queued]


def test_list_filters(store: JobStore) -> None:
    a = store.enqueue("download", "a")
    store.enqueue("ingest", "b")
    assert [j.id for j in store.list_jobs(kind="download")] == [a]
    assert len(store.list_jobs(status=JobStatus.QUEUED)) == 2


def test_prefix_must_be_nblm(redis_client) -> None:
    with pytest.raises(ValueError):
        JobStore(redis_client, prefix="gush.")


def test_every_key_touched_is_under_prefix(store: JobStore) -> None:
    """Fact 3: no key outside the prefix is written, deleted, or scanned."""
    touched: list[str] = []
    real = store.r

    class Spy:
        def __getattr__(self, name):
            attr = getattr(real, name)
            if name == "pipeline":

                def pipeline(*a, **kw):
                    pipe = attr(*a, **kw)
                    return _PipeSpy(pipe, touched)

                return pipeline
            if not callable(attr):
                return attr

            def wrapper(*args, **kwargs):
                if args and isinstance(args[0], str):
                    touched.append(args[0])
                return attr(*args, **kwargs)

            return wrapper

    store.r = Spy()  # type: ignore[assignment]
    job_id = store.enqueue("download", "a")
    store.claim()
    item = store.add_item(job_id, "x")
    store.update_item(job_id, item, status=ItemStatus.DONE)
    store.items(job_id)
    store.finish(job_id, JobStatus.FAILED, error="e")
    store.retry(job_id)
    store.request_cancel(job_id)
    store.mark_interrupted_on_startup()
    store.clear_finished()
    assert touched
    assert all(k.startswith(store.prefix) for k in touched), [
        k for k in touched if not k.startswith(store.prefix)
    ]


class _PipeSpy:
    def __init__(self, pipe, touched: list[str]) -> None:
        self._pipe = pipe
        self._touched = touched

    def __getattr__(self, name):
        attr = getattr(self._pipe, name)
        if name == "execute" or not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            if args and isinstance(args[0], str):
                self._touched.append(args[0])
            attr(*args, **kwargs)
            return self

        return wrapper
