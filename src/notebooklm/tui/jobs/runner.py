"""In-process worker pool that executes queued jobs.

``NOTEBOOKLM_TUI_JOB_WORKERS`` threads (default 2) each loop: claim a job from
the :class:`JobStore`, run its handler under ``asyncio.run`` inside a root
``job.<kind>`` span, and write the final status. No handler may enqueue another
job — ordering between kinds is enforced by prerequisite checks inside the
handler (e.g. ``fact_check`` fails when children lack SFL output).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from collections.abc import Callable, Coroutine, Mapping
from contextlib import nullcontext
from typing import Any

from ..._app.tracing import job_span
from .store import ItemStatus, Job, JobStatus, JobStore

logger = logging.getLogger(__name__)

DEFAULT_WORKERS = 2


class JobCancelled(Exception):
    """Raised by :meth:`JobContext.check_cancelled` when cancel was requested."""


class JobContext:
    """What a handler gets: its job, progress/item helpers, cancel and rate limit.

    ``state`` is the shared ``TUIState`` (or ``None`` in tests). Handlers may
    assign whole keys on it (``state.compiler_state = {...}``) but progress
    belongs in the job store, which the Jobs mode renders.
    """

    def __init__(
        self,
        job: Job,
        store: JobStore,
        *,
        trace_id: str | None = None,
        consume_token: Callable[[], bool] | None = None,
        state: Any = None,
        token_wait_seconds: float = 0.5,
    ) -> None:
        self.job = job
        self.store = store
        self.trace_id = trace_id
        self.state = state
        self._consume_token = consume_token
        self._token_wait = token_wait_seconds

    @property
    def payload(self) -> dict[str, Any]:
        return self.job.payload

    @property
    def notebook_id(self) -> str | None:
        return self.job.notebook_id

    def phase(self, text: str, percent: float | None = None) -> None:
        fields: dict[str, Any] = {"phase": text}
        if percent is not None:
            fields["percent"] = f"{max(0.0, min(100.0, percent)):.1f}"
        self.store.update(self.job.id, **fields)

    def check_cancelled(self) -> None:
        if self.store.is_cancel_requested(self.job.id):
            raise JobCancelled()

    def add_item(self, name: str, kind: str = "") -> str:
        return self.store.add_item(self.job.id, name, kind)

    def item_running(self, item_id: str) -> None:
        self.store.update_item(self.job.id, item_id, status=ItemStatus.RUNNING)

    def item_done(self, item_id: str, *, bytes: int | None = None) -> None:
        fields: dict[str, Any] = {"status": ItemStatus.DONE}
        if bytes is not None:
            fields["bytes"] = bytes
        self.store.update_item(self.job.id, item_id, **fields)

    def item_skipped(self, item_id: str, reason: str = "") -> None:
        self.store.update_item(self.job.id, item_id, status=ItemStatus.SKIPPED, error=reason)

    def item_failed(self, item_id: str, error: str) -> None:
        self.store.update_item(self.job.id, item_id, status=ItemStatus.FAILED, error=error)

    async def acquire_token(self) -> None:
        """Wait for one API token from the shared bucket; honours cancellation."""
        if self._consume_token is None:
            return
        while not self._consume_token():
            self.check_cancelled()
            await asyncio.sleep(self._token_wait)


#: A handler is ``async def handle(ctx: JobContext) -> str | None``; the return
#: value becomes the job's ``summary``. Raising fails the job with the message.
Handler = Callable[[JobContext], Coroutine[Any, Any, str | None]]


def worker_count() -> int:
    try:
        return max(1, int(os.environ.get("NOTEBOOKLM_TUI_JOB_WORKERS", DEFAULT_WORKERS)))
    except ValueError:
        return DEFAULT_WORKERS


class JobRunner:
    def __init__(
        self,
        store: JobStore,
        resolve_handler: Callable[[str], Handler] | Mapping[str, Handler],
        *,
        workers: int | None = None,
        consume_token: Callable[[], bool] | None = None,
        state: Any = None,
        lm: Any = None,
        poll_interval: float = 0.25,
    ) -> None:
        self.store = store
        if isinstance(resolve_handler, Mapping):
            mapping = resolve_handler
            self._resolve: Callable[[str], Handler] = lambda kind: mapping[kind]
        else:
            self._resolve = resolve_handler
        self.workers = workers or worker_count()
        self.consume_token = consume_token
        self.state = state
        #: LM captured on the main thread; bound per worker with ``dspy.context``
        #: (``dspy.configure`` is main-thread only — see CLAUDE.md).
        self.lm = lm
        self.poll_interval = poll_interval
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for n in range(self.workers):
            t = threading.Thread(target=self._loop, name=f"nblm-job-worker-{n}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        deadline = time.monotonic() + timeout
        for t in self._threads:
            t.join(max(0.0, deadline - time.monotonic()))

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                job = self.store.claim()
            except Exception:
                logger.exception("Job claim failed")
                self._stop.wait(self.poll_interval)
                continue
            if job is None:
                self._stop.wait(self.poll_interval)
                continue
            self.run_job(job)

    def run_job(self, job: Job) -> None:
        """Execute one claimed job to a terminal status. Never raises."""
        try:
            handler = self._resolve(job.kind)
        except Exception as e:
            self.store.finish(job.id, JobStatus.FAILED, error=f"No handler for {job.kind!r}: {e}")
            return

        lm_ctx: Any = nullcontext()
        if self.lm is not None:
            import dspy

            lm_ctx = dspy.context(lm=self.lm)

        try:
            with (
                job_span(job.kind, job_id=job.id, notebook_id=job.notebook_id) as trace_id,
                lm_ctx,
            ):
                if trace_id:
                    self.store.update(job.id, trace_id=trace_id)
                ctx = JobContext(
                    job,
                    self.store,
                    trace_id=trace_id,
                    consume_token=self.consume_token,
                    state=self.state,
                )
                summary: str | None = asyncio.run(handler(ctx))
        except JobCancelled:
            self.store.finish(job.id, JobStatus.CANCELLED, error="Cancelled")
        except Exception as e:
            logger.exception("Job %s (%s) failed", job.id, job.kind)
            self.store.finish(job.id, JobStatus.FAILED, error=f"{type(e).__name__}: {e}")
        else:
            self.store.finish(job.id, JobStatus.DONE, summary=summary)
