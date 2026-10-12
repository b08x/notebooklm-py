"""SFL tagging over any corpus scope: run ``SFLEngine`` per child, store ``Clause.sfl``.

Shared by the TUI ``sfl_tag`` job (notebook scope) and the web Corpus Explorer
(document, run or chunk-selection scope). Children are grouped by parent and
each parent's results are committed together, so a cancelled run keeps the
parents it finished.

Threading rule: ``dspy.configure()`` is never called here. Each child runs in
``asyncio.to_thread`` under ``dspy.context(lm=...)`` with the LM configured on
the main thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import dspy
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import ChunkRun, Clause, ParentChunk
from .scope import Scope

SFL_KEYS = ("mood", "modality", "tenor")


@dataclass(frozen=True)
class ChildRow:
    id: int
    parent_id: int
    parent_index: int
    text: str


def default_engine() -> Any:
    from .._preprocessing.sfl_engine import SFLEngine

    return SFLEngine()


async def load_children(
    session_factory: async_sessionmaker[AsyncSession], scope: Scope | str | None
) -> list[ChildRow]:
    """Children in ``scope`` (a notebook id is a notebook scope), by parent index then id."""
    if not isinstance(scope, Scope):
        scope = Scope(notebook_id=scope)
    stmt = (
        select(
            Clause.id.label("id"),
            Clause.parent_id.label("parent_id"),
            ParentChunk.index.label("parent_index"),
            Clause.text.label("text"),
        )
        .join(ChunkRun, Clause.run_id == ChunkRun.id)
        .join(ParentChunk, Clause.parent_id == ParentChunk.id)
        .order_by(ParentChunk.index, Clause.id)
    )
    if scope.is_empty:
        # Historical notebook-less scope: active runs with no notebook.
        stmt = stmt.where(ChunkRun.is_active.is_(True), ChunkRun.notebook_id.is_(None))
    else:
        stmt = scope.apply(stmt)
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


@dataclass
class GroupProgress:
    """Callbacks the caller uses to report per-parent progress."""

    start: Callable[[int, int, int, int], Any]
    """``start(parent_number, n_groups, parent_index, n_children) -> handle``"""
    done: Callable[[Any, int, int, str | None], None]
    """``done(handle, n_children, n_failed, first_error)``"""
    check_cancelled: Callable[[], None] = lambda: None
    child: Callable[[int, int, int], None] = lambda *_: None
    """``child(clauses_done, total, parent_number)`` before and after each child."""


async def tag_children(
    children: list[ChildRow],
    *,
    session_factory: async_sessionmaker[AsyncSession],
    progress: GroupProgress,
    engine: Any = None,
    lm: Any = None,
    save: Callable[..., Awaitable[None]] = save_sfl,
) -> tuple[int, int]:
    """Tag ``children`` parent by parent. Returns ``(tagged, failed)``."""
    engine = engine if engine is not None else default_engine()
    lm = lm if lm is not None else dspy.settings.lm
    groups: dict[int, tuple[int, list[ChildRow]]] = {}
    for child in children:
        groups.setdefault(child.parent_id, (child.parent_index, []))[1].append(child)

    tagged = 0
    failed = 0
    processed = 0
    total = len(children)
    for parent_number, (parent_index, rows) in enumerate(groups.values(), start=1):
        handle = progress.start(parent_number, len(groups), parent_index, len(rows))
        results: dict[int, dict[str, Any]] = {}
        first_error: str | None = None
        error_count = 0
        try:
            for row in rows:
                progress.check_cancelled()
                progress.child(processed, total, parent_number)
                try:
                    output = await asyncio.to_thread(_forward, engine, lm, row.text)
                    results[row.id] = to_sfl(output)
                except Exception as e:
                    error_count += 1
                    first_error = first_error or f"{type(e).__name__}: {e}"
                finally:
                    processed += 1
                    progress.child(processed, total, parent_number)
        finally:
            if results:
                await save(session_factory, results)
        tagged += len(results)
        failed += error_count
        progress.done(handle, len(rows), error_count, first_error)
    return tagged, failed
