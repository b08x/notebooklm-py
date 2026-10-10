"""``sfl_tag`` job handler: run ``SFLEngine`` over a notebook's active-run children.

One job item per parent chunk. Each child gets ``Clause.sfl = {mood, modality,
tenor, pass1[, raw]}``. Results are committed per parent, so a cancelled job
keeps the parents it finished.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import dspy
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ....db.models import ChunkRun, Clause, ParentChunk
from ....db.session import async_session_maker
from ..runner import JobContext

SFL_KEYS = ("mood", "modality", "tenor")


@dataclass(frozen=True)
class ChildRow:
    id: int
    parent_id: int
    parent_index: int
    text: str


def _default_engine() -> Any:
    from ..._preprocessing.sfl_engine import SFLEngine

    return SFLEngine()


async def load_children(
    session_factory: async_sessionmaker[AsyncSession], notebook_id: str | None
) -> list[ChildRow]:
    """Children of the notebook's active runs, ordered by parent index then id."""
    stmt = (
        select(
            Clause.id.label("id"),
            Clause.parent_id.label("parent_id"),
            ParentChunk.index.label("parent_index"),
            Clause.text.label("text"),
        )
        .join(ChunkRun, Clause.run_id == ChunkRun.id)
        .join(ParentChunk, Clause.parent_id == ParentChunk.id)
        .where(ChunkRun.is_active.is_(True), ChunkRun.notebook_id == notebook_id)
        .order_by(ParentChunk.index, Clause.id)
    )
    async with session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return [
        ChildRow(id=row.id, parent_id=row.parent_id, parent_index=row.parent_index, text=row.text)
        for row in rows
    ]


async def save_sfl(
    session_factory: async_sessionmaker[AsyncSession], values: dict[int, dict[str, Any]]
) -> None:
    """Write ``sfl`` for each clause id in one transaction."""
    async with session_factory() as session:
        for clause_id, sfl in values.items():
            await session.execute(update(Clause).where(Clause.id == clause_id).values(sfl=sfl))
        await session.commit()


def to_sfl(output: dict[str, Any]) -> dict[str, Any]:
    """Map ``SFLEngine.forward`` output to the stored ``sfl`` shape.

    Raises ``ValueError`` when ``interpersonal`` is not a mapping.
    """
    pass1 = output.get("ideational", {})
    interpersonal = output.get("interpersonal", {})
    if not isinstance(interpersonal, dict):
        raise ValueError(f"interpersonal is {type(interpersonal).__name__}, expected dict")
    sfl: dict[str, Any] = {key: interpersonal.get(key) for key in SFL_KEYS}
    sfl["pass1"] = pass1
    raw = {k: v for k, v in interpersonal.items() if k not in SFL_KEYS}
    raw.update({k: v for k, v in output.items() if k not in ("ideational", "interpersonal")})
    if raw:
        sfl["raw"] = raw
    return sfl


def _forward(engine: Any, lm: Any, text: str) -> dict[str, Any]:
    with dspy.context(lm=lm):
        return engine.forward(text)


async def run_sfl_tag(
    ctx: JobContext,
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_maker,
    engine_factory: Callable[[], Any] = _default_engine,
    load: Callable[..., Any] = load_children,
    save: Callable[..., Any] = save_sfl,
) -> str:
    children = await load(session_factory, ctx.notebook_id)
    if not children:
        raise RuntimeError("no ingested children; run ingest first")

    engine = engine_factory()
    lm = dspy.settings.lm
    groups: dict[int, tuple[int, list[ChildRow]]] = {}
    for child in children:
        groups.setdefault(child.parent_id, (child.parent_index, []))[1].append(child)

    tagged = 0
    failed = 0
    for parent_number, (parent_index, rows) in enumerate(groups.values(), start=1):
        item = ctx.add_item(f"parent {parent_index}: {len(rows)} children", "sfl_tag")
        ctx.item_running(item)
        ctx.phase(f"parent {parent_number}/{len(groups)}", 100 * (parent_number - 1) / len(groups))
        results: dict[int, dict[str, Any]] = {}
        first_error: str | None = None
        error_count = 0
        try:
            for row in rows:
                ctx.check_cancelled()
                try:
                    output = await asyncio.to_thread(_forward, engine, lm, row.text)
                    results[row.id] = to_sfl(output)
                except Exception as e:
                    error_count += 1
                    first_error = first_error or f"{type(e).__name__}: {e}"
        finally:
            if results:
                await save(session_factory, results)
        tagged += len(results)
        failed += error_count
        if first_error is not None:
            ctx.item_failed(item, f"{error_count}/{len(rows)} children failed: {first_error}")
        else:
            ctx.item_done(item)
    return f"Tagged {tagged} children ({failed} failed)"


async def handle(ctx: JobContext) -> str | None:
    return await run_sfl_tag(ctx)
