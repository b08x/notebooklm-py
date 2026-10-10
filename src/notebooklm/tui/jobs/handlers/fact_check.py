"""``fact_check`` job handler: a thin adapter over :class:`FactCheckRun`.

Prerequisite: every child in scope must have SFL output (``sfl_tag`` run first).
The handler checks that before any checker call and writes nothing if it fails.
The gate runs in ``auto`` mode (rule-based, no human in the loop); the gate
logic itself lives in :mod:`notebooklm._app.factcheck_runs`, shared with the
web Fact-check screen.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from notebooklm._app.fact_checks import ChildClaim, load_children
from notebooklm._app.factcheck_runs import FactChecker, FactCheckRun, require_sfl
from notebooklm.db.session import async_session_maker

from ..runner import JobContext

__all__ = ["FactChecker", "handle", "run_fact_check"]


def _default_checker() -> FactChecker:
    from notebooklm._preprocessing.sift import SiftChecker

    return SiftChecker()


async def run_fact_check(
    ctx: JobContext,
    *,
    session_factory: Callable[[], AbstractAsyncContextManager[Any]] = async_session_maker,
    checker_factory: Callable[[], FactChecker] = _default_checker,
    loader: Callable[..., Awaitable[list[ChildClaim]]] = load_children,
) -> str:
    notebook_id = ctx.notebook_id
    parent_id = ctx.payload.get("parent_id")
    if notebook_id is None and parent_id is None:
        raise ValueError("fact_check needs a notebook or parent scope")

    ctx.phase("loading children")
    async with session_factory() as session:
        children = await loader(session, notebook_id=notebook_id, parent_id=parent_id)

    require_sfl(children)
    if not children:
        return "no children in scope"

    total = len(children)
    job_items: dict[str, str] = {}

    def on_event(event: dict[str, Any]) -> None:
        kind = event["type"]
        if kind == "item_started":
            index = int(event["item_id"])
            item_id = ctx.add_item(event["external_id"], "claim")
            job_items[event["item_id"]] = item_id
            ctx.item_running(item_id)
            ctx.phase(f"checking {index}/{total}", percent=100.0 * (index - 1) / total)
        elif kind == "item_done":
            item = event["item"]
            item_id = job_items[item["item_id"]]
            if item["status"] == "skipped":
                ctx.item_skipped(item_id, item["reason"] or "")
            else:
                ctx.item_done(item_id)
        elif kind == "item_error":
            ctx.item_failed(job_items[event["item_id"]], event["error"])

    run = FactCheckRun(
        children,
        checker=checker_factory(),
        session_factory=session_factory,
        gate_source="rule",
        gate_mode="auto",
        job_id=ctx.job.id,
        trace_id=ctx.trace_id,
        stop_on_error=True,
        before_item=ctx.check_cancelled,
        on_event=on_event,
    )
    await run.run()
    ctx.phase("done", percent=100.0)
    return run.summary()


async def handle(ctx: JobContext) -> str | None:
    return await run_fact_check(ctx)
