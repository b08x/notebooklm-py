"""``sfl_tag`` job handler: a thin adapter over :mod:`notebooklm._app.sfl_tagging`.

One job item per parent chunk. Each child gets ``Clause.sfl = {mood, modality,
tenor, pass1[, raw]}``. Results are committed per parent, so a cancelled job
keeps the parents it finished. The payload may carry a ``scope`` (documents,
runs or chunks); otherwise the job's notebook is the scope.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...._app.scope import Scope
from ...._app.sfl_tagging import (
    SFL_KEYS,
    ChildRow,
    GroupProgress,
    load_children,
    save_sfl,
    tag_children,
    to_sfl,
)
from ...._app.sfl_tagging import default_engine as _default_engine
from ....db.session import async_session_maker
from ..runner import JobContext

__all__ = ["SFL_KEYS", "ChildRow", "load_children", "run_sfl_tag", "save_sfl", "to_sfl"]


async def run_sfl_tag(
    ctx: JobContext,
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_maker,
    engine_factory: Callable[[], Any] = _default_engine,
    load: Callable[..., Any] = load_children,
    save: Callable[..., Any] = save_sfl,
) -> str:
    scope_data = ctx.payload.get("scope")
    scope: Scope | str | None = Scope.from_mapping(scope_data) if scope_data else ctx.notebook_id
    children = await load(session_factory, scope)
    if not children:
        raise RuntimeError("no ingested children; run ingest first")

    def start(number: int, total: int, parent_index: int, n_children: int) -> str:
        item = ctx.add_item(f"parent {parent_index}: {n_children} children", "sfl_tag")
        ctx.item_running(item)
        ctx.phase(f"parent {number}/{total}", 100 * (number - 1) / total)
        return item

    def done(item: str, n_children: int, n_failed: int, first_error: str | None) -> None:
        if first_error is not None:
            ctx.item_failed(item, f"{n_failed}/{n_children} children failed: {first_error}")
        else:
            ctx.item_done(item)

    tagged, failed = await tag_children(
        children,
        session_factory=session_factory,
        progress=GroupProgress(start=start, done=done, check_cancelled=ctx.check_cancelled),
        engine=engine_factory(),
        save=save,
    )
    return f"Tagged {tagged} children ({failed} failed)"


async def handle(ctx: JobContext) -> str | None:
    return await run_sfl_tag(ctx)
