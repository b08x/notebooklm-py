"""Redis-backed job records for the TUI job queue.

Key layout (every key starts with ``prefix``, default ``nblm:``):

* ``{prefix}job:<id>``               hash  — one job record (see :class:`Job`)
* ``{prefix}job:<id>:items``         list  — item ids in insertion order
* ``{prefix}job:<id>:item:<item_id>`` hash — one item record (see :class:`JobItem`)
* ``{prefix}jobs:queued``            zset  — queued job ids, score = enqueue time
* ``{prefix}jobs:all``               zset  — every known job id, score = enqueue time

The Redis instance on this host is shared with Ruby Gush/Ohm workers, so this
module never touches a key outside ``prefix`` and never calls ``FLUSHDB``/``KEYS``.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import redis

DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_PREFIX = "nblm:"
#: Finished job records (and their items) expire after this many seconds.
FINISHED_TTL_SECONDS = 7 * 24 * 3600


class RedisUnavailable(RuntimeError):
    """Redis could not be reached. The TUI and the Redis tests must not continue."""


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


#: Statuses a job can no longer leave on its own; ``clear_finished`` removes these.
FINISHED_STATUSES = frozenset(
    {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.INTERRUPTED}
)


class ItemStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Job:
    id: str
    kind: str
    status: JobStatus
    notebook_id: str | None = None
    phase: str = ""
    percent: float = 0.0
    error: str | None = None
    #: Human-readable result line set by the handler on success.
    summary: str | None = None
    created_at: float = 0.0
    started_at: float | None = None
    finished_at: float | None = None
    trace_id: str | None = None
    cancel_requested: bool = False
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class JobItem:
    id: str
    name: str
    kind: str = ""
    status: ItemStatus = ItemStatus.PENDING
    bytes: int | None = None
    error: str | None = None


def redis_url() -> str:
    return os.environ.get("NOTEBOOKLM_REDIS_URL", DEFAULT_REDIS_URL)


def connect(url: str | None = None) -> redis.Redis:
    """Return a connected client, or raise :class:`RedisUnavailable` naming the URL."""
    url = url or redis_url()
    client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
    try:
        client.ping()
    except redis.RedisError as e:
        raise RedisUnavailable(
            f"Redis unreachable at {url}: {str(e).rstrip('.')}. Start Redis and retry."
        ) from e
    return client


def _enc(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, dict | list):
        return json.dumps(value)
    return str(value)


def _opt_float(raw: str | None) -> float | None:
    return float(raw) if raw else None


class JobStore:
    """CRUD and queue operations over job records. Thread-safe (redis-py pools)."""

    def __init__(
        self,
        client: redis.Redis,
        prefix: str = DEFAULT_PREFIX,
        ttl_seconds: int = FINISHED_TTL_SECONDS,
    ) -> None:
        if not prefix.startswith(DEFAULT_PREFIX):
            raise ValueError(f"prefix must start with {DEFAULT_PREFIX!r}, got {prefix!r}")
        #: ``Any``: redis-py's stubs type replies as ``bytes | str`` regardless of
        #: ``decode_responses=True``, which ``connect`` always sets.
        self.r: Any = client
        self.prefix = prefix
        self.ttl_seconds = ttl_seconds

    # -- keys ---------------------------------------------------------------
    def job_key(self, job_id: str) -> str:
        return f"{self.prefix}job:{job_id}"

    def items_key(self, job_id: str) -> str:
        return f"{self.prefix}job:{job_id}:items"

    def item_key(self, job_id: str, item_id: str) -> str:
        return f"{self.prefix}job:{job_id}:item:{item_id}"

    @property
    def queued_key(self) -> str:
        return f"{self.prefix}jobs:queued"

    @property
    def all_key(self) -> str:
        return f"{self.prefix}jobs:all"

    # -- jobs ---------------------------------------------------------------
    def enqueue(
        self, kind: str, notebook_id: str | None = None, payload: dict[str, Any] | None = None
    ) -> str:
        job_id = uuid.uuid4().hex[:12]
        now = time.time()
        pipe = self.r.pipeline()
        pipe.hset(
            self.job_key(job_id),
            mapping={
                "id": job_id,
                "kind": kind,
                "status": JobStatus.QUEUED.value,
                "notebook_id": notebook_id or "",
                "phase": "Queued",
                "percent": "0",
                "created_at": repr(now),
                "cancel_requested": "0",
                "payload": json.dumps(payload or {}),
            },
        )
        pipe.zadd(self.queued_key, {job_id: now})
        pipe.zadd(self.all_key, {job_id: now})
        pipe.execute()
        return job_id

    def get(self, job_id: str) -> Job | None:
        raw = self.r.hgetall(self.job_key(job_id))
        if not raw:
            return None
        return Job(
            id=raw["id"],
            kind=raw["kind"],
            status=JobStatus(raw["status"]),
            notebook_id=raw.get("notebook_id") or None,
            phase=raw.get("phase", ""),
            percent=float(raw.get("percent") or 0),
            error=raw.get("error") or None,
            summary=raw.get("summary") or None,
            created_at=float(raw.get("created_at") or 0),
            started_at=_opt_float(raw.get("started_at")),
            finished_at=_opt_float(raw.get("finished_at")),
            trace_id=raw.get("trace_id") or None,
            cancel_requested=raw.get("cancel_requested") == "1",
            payload=json.loads(raw.get("payload") or "{}"),
        )

    def update(self, job_id: str, **fields: Any) -> None:
        if fields:
            self.r.hset(self.job_key(job_id), mapping={k: _enc(v) for k, v in fields.items()})

    def claim(self) -> Job | None:
        """Atomically pop the oldest queued job and mark it running."""
        popped = self.r.zpopmin(self.queued_key, 1)
        if not popped:
            return None
        [(job_id, _score)] = popped
        self.update(
            job_id, status=JobStatus.RUNNING, started_at=repr(time.time()), phase="Starting"
        )
        return self.get(job_id)

    def finish(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: str | None = None,
        summary: str | None = None,
    ) -> None:
        fields: dict[str, Any] = {"status": status, "finished_at": repr(time.time())}
        if status == JobStatus.DONE:
            fields["percent"] = "100"
        if error is not None:
            fields["error"] = error
        if summary is not None:
            fields["summary"] = summary
        self.update(job_id, **fields)
        self._expire(job_id)

    def _expire(self, job_id: str) -> None:
        pipe = self.r.pipeline()
        pipe.expire(self.job_key(job_id), self.ttl_seconds)
        pipe.expire(self.items_key(job_id), self.ttl_seconds)
        for item_id in self.r.lrange(self.items_key(job_id), 0, -1):
            pipe.expire(self.item_key(job_id, item_id), self.ttl_seconds)
        pipe.execute()

    def _persist(self, job_id: str) -> None:
        pipe = self.r.pipeline()
        pipe.persist(self.job_key(job_id))
        pipe.persist(self.items_key(job_id))
        pipe.execute()

    def request_cancel(self, job_id: str) -> None:
        """Queued: removed from the queue and cancelled. Running: flagged; the
        handler stops at its next ``check_cancelled``."""
        job = self.get(job_id)
        if job is None:
            return
        if job.status == JobStatus.QUEUED:
            self.r.zrem(self.queued_key, job_id)
            self.finish(job_id, JobStatus.CANCELLED, error="Cancelled before start")
        elif job.status == JobStatus.RUNNING:
            self.update(job_id, cancel_requested=True)

    def is_cancel_requested(self, job_id: str) -> bool:
        return self.r.hget(self.job_key(job_id), "cancel_requested") == "1"

    def retry(self, job_id: str) -> bool:
        """Re-queue a failed/interrupted/cancelled job under the same id.

        Items are cleared; handlers are idempotent (downloads skip ``LocalAsset``
        rows, ingest writes a new run), so re-running the whole job is safe.
        """
        job = self.get(job_id)
        if job is None or job.status not in FINISHED_STATUSES - {JobStatus.DONE}:
            return False
        self._clear_items(job_id)
        self._persist(job_id)
        self.r.hdel(self.job_key(job_id), "error", "summary", "finished_at", "started_at")
        self.update(
            job_id, status=JobStatus.QUEUED, phase="Queued", percent="0", cancel_requested=False
        )
        self.r.zadd(self.queued_key, {job_id: time.time()})
        return True

    def clear_finished(self) -> int:
        cleared = 0
        for job in self.list_jobs():
            if job.status in FINISHED_STATUSES:
                self._delete(job.id)
                cleared += 1
        return cleared

    def _clear_items(self, job_id: str) -> None:
        item_ids = self.r.lrange(self.items_key(job_id), 0, -1)
        keys = [self.item_key(job_id, i) for i in item_ids] + [self.items_key(job_id)]
        self.r.delete(*keys)

    def _delete(self, job_id: str) -> None:
        self._clear_items(job_id)
        pipe = self.r.pipeline()
        pipe.delete(self.job_key(job_id))
        pipe.zrem(self.all_key, job_id)
        pipe.zrem(self.queued_key, job_id)
        pipe.execute()

    def list_jobs(self, kind: str | None = None, status: JobStatus | None = None) -> list[Job]:
        """Jobs newest first. Ids whose record expired are pruned from the index."""
        jobs: list[Job] = []
        for job_id in self.r.zrevrange(self.all_key, 0, -1):
            job = self.get(job_id)
            if job is None:
                self.r.zrem(self.all_key, job_id)
                continue
            if kind is not None and job.kind != kind:
                continue
            if status is not None and job.status != status:
                continue
            jobs.append(job)
        return jobs

    def running_count(self) -> int:
        return len(self.list_jobs(status=JobStatus.RUNNING))

    def mark_interrupted_on_startup(self) -> int:
        """Set every ``running`` job to ``interrupted`` (the previous TUI died)."""
        count = 0
        for job in self.list_jobs(status=JobStatus.RUNNING):
            self.finish(job.id, JobStatus.INTERRUPTED, error="TUI exited while running")
            count += 1
        return count

    # -- items --------------------------------------------------------------
    def add_item(self, job_id: str, name: str, kind: str = "") -> str:
        item_id = uuid.uuid4().hex[:8]
        pipe = self.r.pipeline()
        pipe.hset(
            self.item_key(job_id, item_id),
            mapping={"id": item_id, "name": name, "kind": kind, "status": ItemStatus.PENDING.value},
        )
        pipe.rpush(self.items_key(job_id), item_id)
        pipe.execute()
        return item_id

    def update_item(self, job_id: str, item_id: str, **fields: Any) -> None:
        if fields:
            self.r.hset(
                self.item_key(job_id, item_id), mapping={k: _enc(v) for k, v in fields.items()}
            )

    def items(self, job_id: str) -> list[JobItem]:
        out: list[JobItem] = []
        for item_id in self.r.lrange(self.items_key(job_id), 0, -1):
            raw = self.r.hgetall(self.item_key(job_id, item_id))
            if not raw:
                continue
            out.append(
                JobItem(
                    id=raw["id"],
                    name=raw.get("name", ""),
                    kind=raw.get("kind", ""),
                    status=ItemStatus(raw.get("status", ItemStatus.PENDING.value)),
                    bytes=int(raw["bytes"]) if raw.get("bytes") else None,
                    error=raw.get("error") or None,
                )
            )
        return out
