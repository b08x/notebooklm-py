"""``download`` job handler. Stub — implemented in wave 1 (see goals/tui-job-queue-and-workbench-layout/plan.md)."""

from __future__ import annotations

from ..runner import JobContext


async def handle(ctx: JobContext) -> str | None:
    raise NotImplementedError("download handler not implemented yet")
