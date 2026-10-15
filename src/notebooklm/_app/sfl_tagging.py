"""SFL tagging over any corpus scope: run ``SFLEngine`` per child, store ``Clause.sfl``.

Shared by the TUI ``sfl_tag`` job (notebook scope) and the web Corpus Explorer
(document, run or chunk-selection scope). Children are grouped by parent and
each parent's results are committed together, so a cancelled run keeps the
parents it finished.

The engine backend comes from ``NOTEBOOKLM_SFL_BACKEND``: ``dspy`` (default)
or a CLI coding agent name (``claude``, ``agy``, ``vibe``, ``opencode``), which
selects :class:`~notebooklm._preprocessing.cli_agents.AgentSFLEngine`. An engine
with ``forward_batch`` receives each parent's children in one call.

Threading rule: ``dspy.configure()`` is never called here. Each child (or
parent batch) runs in ``asyncio.to_thread`` under ``dspy.context(lm=...)`` with
the LM configured on the main thread.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

import dspy
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import ChunkRun, Clause, ParentChunk
from .scope import Scope

SFL_KEYS = ("mood", "modality", "tenor")
#: Textual metafunction keys the CLI-agent backend adds; stored when present.
SFL_TEXTUAL_KEYS = ("theme", "rheme", "cohesive_markers")


@dataclass(frozen=True)
class ChildRow:
    id: int
    parent_id: int
    parent_index: int
    text: str


SFL_BACKEND_ENV = "NOTEBOOKLM_SFL_BACKEND"
SFL_AGENT_MODEL_ENV = "NOTEBOOKLM_SFL_AGENT_MODEL"
SFL_AGENT_TIMEOUT_ENV = "NOTEBOOKLM_SFL_AGENT_TIMEOUT"
SFL_AGENT_BATCH_ENV = "NOTEBOOKLM_SFL_AGENT_BATCH"
SFL_AGENT_FALLBACK_ENV = "NOTEBOOKLM_SFL_AGENT_FALLBACK"
SFL_AGENT_PROFILE_ENV = "NOTEBOOKLM_SFL_AGENT_PROFILE"
SFL_AGENT_WORKDIR_ENV = "NOTEBOOKLM_SFL_AGENT_WORKDIR"
DSPY_BACKEND = "dspy"
_FALSE = {"0", "false", "no", "off"}


def resolve_backend(backend: str | None = None) -> str:
    """``backend`` if given, else ``$NOTEBOOKLM_SFL_BACKEND``, else ``dspy``."""
    value = backend if backend is not None else os.environ.get(SFL_BACKEND_ENV, "")
    return value.strip().lower() or DSPY_BACKEND


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in _FALSE


def default_engine(
    backend: str | None = None,
    *,
    model: str | None = None,
    timeout: float | None = None,
    batch: bool | None = None,
    fallback: bool | None = None,
    agent_profile: str | None = None,
    workdir: str | None = None,
) -> Any:
    """The SFL engine for ``backend`` (see :func:`resolve_backend`).

    Unset keyword arguments read ``NOTEBOOKLM_SFL_AGENT_MODEL`` / ``_TIMEOUT`` /
    ``_BATCH`` / ``_FALLBACK`` / ``_PROFILE`` / ``_WORKDIR``. The profile is the
    named agent each CLI loads (default ``sfl-annotator``; empty = none).
    Raises ``ValueError`` for an unknown backend.
    """
    name = resolve_backend(backend)
    if name == DSPY_BACKEND:
        from .._preprocessing.sfl_engine import SFLEngine

        return SFLEngine()

    from .._preprocessing.cli_agents import AgentSFLEngine, get_adapter
    from .._preprocessing.cli_agents.sfl_engine import DEFAULT_AGENT_PROFILE

    if timeout is None:
        raw_timeout = os.environ.get(SFL_AGENT_TIMEOUT_ENV, "").strip()
        timeout = float(raw_timeout) if raw_timeout else None
    if agent_profile is None:
        agent_profile = os.environ.get(SFL_AGENT_PROFILE_ENV, DEFAULT_AGENT_PROFILE)
    adapter_kwargs: dict[str, Any] = {
        "model": model or os.environ.get(SFL_AGENT_MODEL_ENV) or None,
        "agent": agent_profile.strip() or None,
        "workdir": workdir or os.path.expanduser(os.environ.get(SFL_AGENT_WORKDIR_ENV, "")) or None,
    }
    if timeout is not None:
        adapter_kwargs["timeout"] = timeout
    adapter = get_adapter(name, **adapter_kwargs)
    return AgentSFLEngine(
        adapter,
        batch=_env_flag(SFL_AGENT_BATCH_ENV, True) if batch is None else batch,
        fallback=_env_flag(SFL_AGENT_FALLBACK_ENV, True) if fallback is None else fallback,
    )


def engine_backend(engine: Any) -> str:
    """Label of ``engine``'s backend for reports (``dspy`` or ``agent:<name>``)."""
    return str(getattr(engine, "backend", DSPY_BACKEND))


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
    sfl.update({key: interpersonal[key] for key in SFL_TEXTUAL_KEYS if key in interpersonal})
    sfl["pass1"] = pass1
    stored = SFL_KEYS + SFL_TEXTUAL_KEYS
    raw = {k: v for k, v in interpersonal.items() if k not in stored}
    raw.update({k: v for k, v in output.items() if k not in ("ideational", "interpersonal")})
    if raw:
        sfl["raw"] = raw
    return sfl


def _forward(engine: Any, lm: Any, text: str) -> dict[str, Any]:
    with dspy.context(lm=lm):
        return engine.forward(text)


def _forward_batch(engine: Any, lm: Any, texts: list[str]) -> list[Any]:
    with dspy.context(lm=lm):
        return list(engine.forward_batch(texts))


def _batches(engine: Any) -> bool:
    return callable(getattr(engine, "forward_batch", None)) and bool(getattr(engine, "batch", True))


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
    """Tag ``children`` parent by parent. Returns ``(tagged, failed)``.

    An engine with ``forward_batch`` (and ``batch`` not false) gets each
    parent's children in one call; ``progress.child`` then fires once before
    and once after the parent instead of around every child.
    """
    engine = engine if engine is not None else default_engine()
    lm = lm if lm is not None else dspy.settings.lm
    batched = _batches(engine)
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
            if batched:
                progress.check_cancelled()
                progress.child(processed, total, parent_number)
                try:
                    outputs: list[Any] = await asyncio.to_thread(
                        _forward_batch, engine, lm, [row.text for row in rows]
                    )
                    if len(outputs) != len(rows):
                        raise ValueError(
                            f"engine returned {len(outputs)} results for {len(rows)} children"
                        )
                except Exception as e:
                    outputs = [e] * len(rows)
                for row, output in zip(rows, outputs, strict=True):
                    try:
                        if isinstance(output, BaseException):
                            raise output
                        results[row.id] = to_sfl(output)
                    except Exception as e:
                        error_count += 1
                        first_error = first_error or f"{type(e).__name__}: {e}"
                processed += len(rows)
                progress.child(processed, total, parent_number)
                rows_to_tag: list[ChildRow] = []
            else:
                rows_to_tag = rows
            for row in rows_to_tag:
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


class AmbiguousNotebookError(ValueError):
    """A notebook ID prefix matches more than one corpus notebook."""

    def __init__(self, prefix: str, candidates: list[str]) -> None:
        super().__init__(f"notebook prefix {prefix!r} matches {len(candidates)} corpus notebooks")
        self.prefix = prefix
        self.candidates = candidates


async def resolve_corpus_notebook(
    session_factory: async_sessionmaker[AsyncSession], notebook_id: str
) -> str:
    """Expand a notebook ID prefix to the one corpus notebook it names.

    An exact match wins; otherwise a unique prefix match. A prefix matching
    nothing is returned unchanged (the scope then loads no children).
    Raises :class:`AmbiguousNotebookError` when several notebooks match.
    """
    stmt = (
        select(ChunkRun.notebook_id)
        .where(ChunkRun.notebook_id.startswith(notebook_id, autoescape=True))
        .distinct()
    )
    async with session_factory() as session:
        ids = sorted(row[0] for row in (await session.execute(stmt)).all() if row[0])
    if notebook_id in ids or not ids:
        return notebook_id
    if len(ids) == 1:
        return ids[0]
    raise AmbiguousNotebookError(notebook_id, ids)


@dataclass(frozen=True)
class ParentOutcome:
    parent_index: int
    children: int
    failed: int
    first_error: str | None


@dataclass(frozen=True)
class TagSFLReport:
    """Result of :func:`run_tag_sfl`."""

    backend: str
    children: int
    parents: list[ParentOutcome]
    tagged: int
    failed: int


async def run_tag_sfl(
    scope: Scope | str | None,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    engine: Any,
    lm: Any = None,
    on_parent: Callable[[int, int, ParentOutcome], None] | None = None,
    load: Callable[..., Awaitable[list[ChildRow]]] = load_children,
    save: Callable[..., Awaitable[None]] = save_sfl,
    resolve_notebook: Callable[..., Awaitable[str]] | None = resolve_corpus_notebook,
) -> TagSFLReport:
    """Load the children in ``scope`` and tag them; ``children == 0`` means nothing to tag.

    A notebook ID in ``scope`` may be a prefix (see :func:`resolve_corpus_notebook`).
    ``on_parent(parent_number, n_parents, outcome)`` fires after each parent commits.
    """
    if not isinstance(scope, Scope):
        scope = Scope(notebook_id=scope)
    if scope.notebook_id and resolve_notebook is not None:
        scope = replace(
            scope, notebook_id=await resolve_notebook(session_factory, scope.notebook_id)
        )
    children = await load(session_factory, scope)
    backend = engine_backend(engine)
    if not children:
        return TagSFLReport(backend=backend, children=0, parents=[], tagged=0, failed=0)

    outcomes: list[ParentOutcome] = []

    def start(number: int, n_groups: int, parent_index: int, n_children: int) -> Any:
        return (number, n_groups, parent_index)

    def done(handle: Any, n_children: int, n_failed: int, first_error: str | None) -> None:
        number, n_groups, parent_index = handle
        outcome = ParentOutcome(parent_index, n_children, n_failed, first_error)
        outcomes.append(outcome)
        if on_parent is not None:
            on_parent(number, n_groups, outcome)

    tagged, failed = await tag_children(
        children,
        session_factory=session_factory,
        progress=GroupProgress(start=start, done=done),
        engine=engine,
        lm=lm,
        save=save,
    )
    return TagSFLReport(
        backend=backend, children=len(children), parents=outcomes, tagged=tagged, failed=failed
    )
