"""``fact_check`` job handler: gate each child, check the claims, append verdict rows.

Prerequisite: every child in scope must have SFL output (``sfl_tag`` run first).
The handler checks that before any checker call and writes nothing if it fails.
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from notebooklm._app.fact_checks import (
    ChildClaim,
    VerdictResult,
    load_children,
    record_fact_check,
    record_not_checkworthy,
)
from notebooklm._preprocessing.checkworthiness import assess
from notebooklm.db.session import async_session_maker

from ..runner import JobContext


class FactChecker(Protocol):
    @property
    def framework_available(self) -> bool: ...

    async def check(
        self, claim: str, parent_context: str, sfl: dict[str, Any] | None
    ) -> VerdictResult: ...


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

    untagged = sum(1 for child in children if child.sfl is None)
    if untagged:
        raise RuntimeError(f"run sfl_tag first ({untagged} children untagged)")
    if not children:
        return "no children in scope"

    checker = checker_factory()
    counts: Counter[str] = Counter()
    total = len(children)
    for index, child in enumerate(children, start=1):
        ctx.check_cancelled()
        item_id = ctx.add_item(child.external_id, "claim")
        ctx.item_running(item_id)
        ctx.phase(f"checking {index}/{total}", percent=100.0 * (index - 1) / total)

        checkworthy, reason = assess(child.sfl, child.tokens)
        async with session_factory() as session:
            if not checkworthy:
                await record_not_checkworthy(
                    session, child.external_id, job_id=ctx.job.id, trace_id=ctx.trace_id
                )
                ctx.item_skipped(item_id, reason)
                counts["not_checkworthy"] += 1
                continue

            started = time.perf_counter()
            try:
                result = await checker.check(child.text, child.parent_text or "", child.sfl)
            except Exception as e:
                ctx.item_failed(item_id, f"{type(e).__name__}: {e}")
                raise
            latency_ms = round((time.perf_counter() - started) * 1000)
            await record_fact_check(
                session,
                child.external_id,
                result,
                job_id=ctx.job.id,
                trace_id=ctx.trace_id,
                latency_ms=latency_ms,
            )
        ctx.item_done(item_id)
        counts[result.verdict] += 1

    ctx.phase("done", percent=100.0)
    parts = ", ".join(
        f"{verdict} {counts[verdict]}"
        for verdict in (
            "supported",
            "contradicted",
            "unverifiable",
            "skipped_no_framework",
            "not_checkworthy",
        )
    )
    return f"fact-checked {total} children: {parts}"


async def handle(ctx: JobContext) -> str | None:
    return await run_fact_check(ctx)
