"""In-process background jobs for long corpus work (artifact ingest, SFL tagging).

A :class:`BackgroundJob` runs one coroutine on the server loop and records its
progress as seq-numbered events, so the web UI can follow it over SSE (with
``after=<seq>`` replay) and the status footer can show what is running. Jobs
live in a :class:`JobRegistry` on the server's app state, independent of any
connection. Documents a running job writes to are reported as *busy*, so a
concurrent document/run delete can be refused.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import nullcontext
from typing import Any

from .tracing import job_span, trace_url

logger = logging.getLogger(__name__)

EVENT_BUFFER = 2000


class BackgroundJob:
    def __init__(
        self,
        kind: str,
        label: str,
        *,
        document_ids: set[str] | None = None,
        traced: bool = False,
    ) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.kind = kind
        self.label = label
        self.document_ids = set(document_ids or ())
        self.traced = traced
        self.status = "queued"
        self.message = ""
        self.done = 0
        self.total = 0
        self.result: Any = None
        self.error: str | None = None
        self.trace_id: str | None = None
        self.created_at = time.time()
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER)
        self._seq = 0
        self._changed = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def finished(self) -> bool:
        return self.status in ("done", "failed", "cancelled")

    def emit(self, type_: str, **data: Any) -> None:
        self._seq += 1
        self._events.append(
            {"seq": self._seq, "job_id": self.id, "ts": time.time(), "type": type_, **data}
        )
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()

    def progress(self, message: str, done: int | None = None, total: int | None = None) -> None:
        self.message = message
        if done is not None:
            self.done = done
        if total is not None:
            self.total = total
        self.emit("progress", message=message, done=self.done, total=self.total)

    def events_after(self, after_seq: int) -> list[dict[str, Any]]:
        return [e for e in self._events if e["seq"] > after_seq]

    async def subscribe(self, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        cursor = after_seq
        while True:
            changed = self._changed
            pending = self.events_after(cursor)
            for event in pending:
                cursor = event["seq"]
                yield event
            if pending:
                continue
            if self.finished:
                return
            await changed.wait()

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "done": self.done,
            "total": self.total,
            "result": self.result,
            "error": self.error,
            "document_ids": sorted(self.document_ids),
            "trace_url": trace_url(self.trace_id),
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_seq": self._seq,
        }

    async def _run(self, body: Callable[[BackgroundJob], Coroutine[Any, Any, Any]]) -> None:
        self.status = "running"
        self.started_at = time.time()
        self.emit("started", label=self.label)
        logger.info("job_id=%s kind=%s started label=%r", self.id, self.kind, self.label)
        try:
            with (
                job_span(self.kind, job_id=self.id, label=self.label)
                if self.traced
                else nullcontext(None)
            ) as trace_id:
                self.trace_id = trace_id if self.traced else None
                self.result = await body(self)
            self.status = "done"
            logger.info("job_id=%s kind=%s done", self.id, self.kind)
        except asyncio.CancelledError:
            self.status = "cancelled"
            raise
        except Exception as e:
            self.status = "failed"
            self.error = f"{type(e).__name__}: {e}"
            logger.error(
                "job_id=%s kind=%s failed error=%s", self.id, self.kind, self.error, exc_info=True
            )
        finally:
            self.finished_at = time.time()
            self.emit("finished", status=self.status, result=self.result, error=self.error)

    def cancel(self) -> None:
        if self._task is not None and not self.finished:
            self._task.cancel()


class JobRegistry:
    def __init__(self, keep: int = 100) -> None:
        self._jobs: dict[str, BackgroundJob] = {}
        self._keep = keep

    def start(
        self,
        kind: str,
        label: str,
        body: Callable[[BackgroundJob], Coroutine[Any, Any, Any]],
        *,
        document_ids: set[str] | None = None,
        traced: bool = False,
    ) -> BackgroundJob:
        """Create a job and run ``body(job)`` in the background on the current loop."""
        job = BackgroundJob(kind, label, document_ids=document_ids, traced=traced)
        self._jobs[job.id] = job
        finished = [j for j in self._jobs.values() if j.finished]
        for old in finished[: max(0, len(self._jobs) - self._keep)]:
            self._jobs.pop(old.id, None)
        job._task = asyncio.get_running_loop().create_task(job._run(body))
        return job

    def get(self, job_id: str) -> BackgroundJob | None:
        return self._jobs.get(job_id)

    def all(self) -> list[BackgroundJob]:
        return list(self._jobs.values())

    def active(self) -> list[BackgroundJob]:
        return [j for j in self._jobs.values() if not j.finished]

    def busy_document_ids(self) -> set[str]:
        busy: set[str] = set()
        for job in self.active():
            busy |= job.document_ids
        return busy

    async def shutdown(self) -> None:
        tasks = [j._task for j in self.active() if j._task is not None]
        for job in self.active():
            job.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
