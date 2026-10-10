"""Live-Redis fixtures for job-store tests.

These tests FAIL (never skip) when Redis is unreachable: the TUI cannot run
without it, so a missing Redis is an environment error to fix, not a reason to
silently drop coverage. Each test gets a unique ``nblm:test:<uuid>:`` prefix and
deletes only keys under that prefix (the instance is shared with Ruby workers).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest

from notebooklm.tui.jobs.store import JobStore, RedisUnavailable, connect, redis_url


@pytest.fixture(scope="session")
def redis_client():
    try:
        return connect()
    except RedisUnavailable as e:
        pytest.fail(f"{e} (set NOTEBOOKLM_REDIS_URL; current {redis_url()})", pytrace=False)


@pytest.fixture
def store(redis_client) -> Iterator[JobStore]:
    prefix = f"nblm:test:{uuid.uuid4().hex[:10]}:"
    yield JobStore(redis_client, prefix=prefix)
    keys = list(redis_client.scan_iter(match=f"{prefix}*", count=500))
    if keys:
        redis_client.delete(*keys)
