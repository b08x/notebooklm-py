"""TUI job queue: Redis-backed records (``store``), worker pool (``runner``),
and per-kind handlers (``handlers/<kind>.py``, resolved via ``kinds``)."""

from .kinds import JOB_KINDS, resolve_handler
from .runner import Handler, JobCancelled, JobContext, JobRunner
from .store import (
    ItemStatus,
    Job,
    JobItem,
    JobStatus,
    JobStore,
    RedisUnavailable,
    connect,
)

__all__ = [
    "JOB_KINDS",
    "Handler",
    "ItemStatus",
    "Job",
    "JobCancelled",
    "JobContext",
    "JobItem",
    "JobRunner",
    "JobStatus",
    "JobStore",
    "RedisUnavailable",
    "connect",
    "resolve_handler",
]
