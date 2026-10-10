"""Corpus Explorer mutations: confirmed hard delete and export.

Delete works at four levels — a clause, a parent chunk (with its children), a
whole document (every run), or a whole run. The flow is always two-step:

1. :func:`delete_preview` counts what would go (clauses, embeddings,
   fact-checks, parents, runs) and changes nothing;
2. :func:`delete` removes it in one transaction and writes one ``removal_log``
   row per deleted item (``action="delete_local"``).

``embeddings.clause_id`` and ``fact_checks.clause_external_id`` cascade from
``clauses``; ``clauses`` and ``parent_chunks`` cascade from ``chunk_runs`` and
``parent_chunks``. Deletes still run child-first explicitly so the receipt's
counts are exact and nothing depends on a cascade being present.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, cast

from sqlalchemy import ColumnElement, CursorResult, func, select
from sqlalchemy import delete as sql_delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ChunkRun, Clause, Embedding, FactCheck, ParentChunk, RemovalLog
from .curation import REMOVAL_REASONS

DeleteLevel = Literal["clause", "parent", "document", "run"]
DELETE_LEVELS: tuple[str, ...] = ("clause", "parent", "document", "run")
EXPORT_FORMATS = ("markdown", "json")


@dataclass
class DeleteCounts:
    clauses: int = 0
    embeddings: int = 0
    fact_checks: int = 0
    parents: int = 0
    runs: int = 0


@dataclass
class DeleteReceipt:
    level: str
    ids: list[str]
    counts: DeleteCounts
    removal_log_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "ids": self.ids,
            "counts": asdict(self.counts),
            "removal_log_ids": self.removal_log_ids,
        }


class DeleteRefusedError(RuntimeError):
    """The target is busy (e.g. its ingestion is still writing)."""


def _validate(level: str, ids: Sequence[str | int], reason: str) -> list[str]:
    if level not in DELETE_LEVELS:
        raise ValueError(f"level must be one of {DELETE_LEVELS}, got {level!r}")
    if reason not in REMOVAL_REASONS:
        raise ValueError(f"reason must be one of {REMOVAL_REASONS}, got {reason!r}")
    clean = [str(i) for i in ids if str(i).strip()]
    if not clean:
        raise ValueError("ids must not be empty")
    if level in ("parent", "run"):
        for i in clean:
            if not i.isdigit():
                raise ValueError(f"{level} ids are integers, got {i!r}")
    return clean


def _clause_condition(level: str, ids: list[str]) -> ColumnElement[bool]:
    if level == "clause":
        return Clause.external_id.in_(ids)
    if level == "parent":
        return Clause.parent_id.in_([int(i) for i in ids])
    if level == "document":
        return Clause.document_id.in_(ids)
    return Clause.run_id.in_([int(i) for i in ids])


def _parent_condition(level: str, ids: list[str]) -> ColumnElement[bool] | None:
    if level == "parent":
        return ParentChunk.id.in_([int(i) for i in ids])
    if level == "document":
        return ParentChunk.document_id.in_(ids)
    if level == "run":
        return ParentChunk.run_id.in_([int(i) for i in ids])
    return None


def _run_condition(level: str, ids: list[str]) -> ColumnElement[bool] | None:
    if level == "document":
        return ChunkRun.document_id.in_(ids)
    if level == "run":
        return ChunkRun.id.in_([int(i) for i in ids])
    return None


async def _deleted(session: AsyncSession, stmt: Any) -> int:
    result = cast("CursorResult[Any]", await session.execute(stmt))
    return int(result.rowcount or 0)


async def _count(session: AsyncSession, stmt: Any) -> int:
    return int((await session.execute(stmt)).scalar_one())


async def delete_preview(
    session: AsyncSession, level: str, ids: Sequence[str | int], reason: str = "other"
) -> dict[str, Any]:
    """Counts per table that :func:`delete` would remove. Writes nothing."""
    clean = _validate(level, ids, reason)
    clause_ids = select(Clause.external_id).where(_clause_condition(level, clean))
    counts = DeleteCounts(
        clauses=await _count(
            session, select(func.count(Clause.id)).where(_clause_condition(level, clean))
        ),
        embeddings=await _count(
            session, select(func.count(Embedding.id)).where(Embedding.clause_id.in_(clause_ids))
        ),
        fact_checks=await _count(
            session,
            select(func.count(FactCheck.id)).where(FactCheck.clause_external_id.in_(clause_ids)),
        ),
    )
    parent_cond = _parent_condition(level, clean)
    if parent_cond is not None:
        counts.parents = await _count(
            session, select(func.count(ParentChunk.id)).where(parent_cond)
        )
    run_cond = _run_condition(level, clean)
    if run_cond is not None:
        counts.runs = await _count(session, select(func.count(ChunkRun.id)).where(run_cond))
    return {"level": level, "ids": clean, "counts": asdict(counts)}


async def _log_targets(
    session: AsyncSession, level: str, ids: list[str]
) -> list[tuple[str, str, str]]:
    """``(item_id, notebook_id, title)`` for each target, read before deleting."""
    if level == "clause":
        stmt = (
            select(Clause.external_id, ChunkRun.notebook_id, ChunkRun.params)
            .join(ChunkRun, ChunkRun.id == Clause.run_id, isouter=True)
            .where(Clause.external_id.in_(ids))
        )
    elif level == "parent":
        stmt = (
            select(ParentChunk.id, ChunkRun.notebook_id, ChunkRun.params)
            .join(ChunkRun, ChunkRun.id == ParentChunk.run_id)
            .where(ParentChunk.id.in_([int(i) for i in ids]))
        )
    elif level == "run":
        stmt = select(ChunkRun.id, ChunkRun.notebook_id, ChunkRun.params).where(
            ChunkRun.id.in_([int(i) for i in ids])
        )
    else:
        stmt = (
            select(ChunkRun.document_id, ChunkRun.notebook_id, ChunkRun.params)
            .where(ChunkRun.document_id.in_(ids))
            .order_by(ChunkRun.id.desc())
        )
    seen: dict[str, tuple[str, str, str]] = {}
    for item_id, notebook_id, params in (await session.execute(stmt)).all():
        key = str(item_id)
        if key not in seen:
            title = (params or {}).get("title") or key
            seen[key] = (key, notebook_id or "", str(title))
    # Targets with no run (orphan clause/document rows) still get a log row.
    for i in ids:
        seen.setdefault(i, (i, "", i))
    return [seen[i] for i in ids if i in seen]


async def delete(
    session: AsyncSession,
    level: str,
    ids: Sequence[str | int],
    reason: str,
    *,
    busy_document_ids: set[str] | None = None,
) -> DeleteReceipt:
    """Hard-delete the targets in one transaction and log each to ``removal_log``.

    Raises :class:`DeleteRefusedError` for a document/run delete whose document
    is in ``busy_document_ids`` (its ingestion is still writing).
    """
    clean = _validate(level, ids, reason)
    if busy_document_ids and level in ("document", "run"):
        if level == "document":
            busy = busy_document_ids.intersection(clean)
        else:
            run_docs = (
                await session.execute(
                    select(ChunkRun.document_id).where(ChunkRun.id.in_([int(i) for i in clean]))
                )
            ).scalars()
            busy = busy_document_ids.intersection(run_docs)
        if busy:
            raise DeleteRefusedError(f"ingestion still running for {sorted(busy)}")

    targets = await _log_targets(session, level, clean)
    clause_cond = _clause_condition(level, clean)
    clause_ids = select(Clause.external_id).where(clause_cond).scalar_subquery()
    counts = DeleteCounts()
    counts.fact_checks = await _deleted(
        session, sql_delete(FactCheck).where(FactCheck.clause_external_id.in_(clause_ids))
    )
    counts.embeddings = await _deleted(
        session, sql_delete(Embedding).where(Embedding.clause_id.in_(clause_ids))
    )
    counts.clauses = await _deleted(session, sql_delete(Clause).where(clause_cond))
    parent_cond = _parent_condition(level, clean)
    if parent_cond is not None:
        counts.parents = await _deleted(session, sql_delete(ParentChunk).where(parent_cond))
    run_cond = _run_condition(level, clean)
    if run_cond is not None:
        counts.runs = await _deleted(session, sql_delete(ChunkRun).where(run_cond))

    logs = [
        RemovalLog(
            notebook_id=notebook_id,
            notebook_title=notebook_id,
            item_id=item_id,
            item_title=title,
            item_type=level,
            action="delete_local",
            reason=reason,
        )
        for item_id, notebook_id, title in targets
    ]
    session.add_all(logs)
    await session.flush()
    log_ids = [log.id for log in logs]
    await session.commit()
    return DeleteReceipt(level=level, ids=clean, counts=counts, removal_log_ids=log_ids)


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


async def _export_rows(session: AsyncSession, external_ids: Sequence[str]) -> list[dict[str, Any]]:
    stmt = (
        select(Clause, ChunkRun)
        .join(ChunkRun, ChunkRun.id == Clause.run_id, isouter=True)
        .where(Clause.external_id.in_(list(external_ids)))
    )
    order = {eid: i for i, eid in enumerate(external_ids)}
    rows = [
        {
            "external_id": c.external_id,
            "document_id": c.document_id,
            "notebook_id": run.notebook_id if run else None,
            "run_id": c.run_id,
            "sentence_index": c.sentence_index,
            "title": ((run.params or {}).get("title") if run else None),
            "text": c.text,
            "sfl": c.sfl,
            "fact_check_passed": c.fact_check_passed,
        }
        for c, run in (await session.execute(stmt)).all()
    ]
    return sorted(rows, key=lambda r: order.get(r["external_id"], 0))


def render_markdown(rows: list[dict[str, Any]], heading: str = "Corpus export") -> str:
    """Chunks as Markdown, grouped by document, one blockquote per chunk."""
    by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_doc[row["document_id"]].append(row)
    lines = [f"# {heading}", ""]
    for document_id, items in by_doc.items():
        title = items[0].get("title") or document_id
        lines += [f"## {title}", "", f"`{document_id}`", ""]
        for item in items:
            quoted = "\n".join(f"> {line}" if line else ">" for line in item["text"].splitlines())
            lines += [quoted, "", f"<sub>{item['external_id']}</sub>", ""]
    return "\n".join(lines).rstrip() + "\n"


async def export(session: AsyncSession, external_ids: Sequence[str], fmt: str) -> dict[str, Any]:
    """Export chunks as ``markdown`` or ``json``: ``{filename, media_type, content}``."""
    if fmt not in EXPORT_FORMATS:
        raise ValueError(f"fmt must be one of {EXPORT_FORMATS}, got {fmt!r}")
    rows = await _export_rows(session, external_ids)
    if fmt == "json":
        return {
            "filename": "corpus-export.json",
            "media_type": "application/json",
            "content": json.dumps({"chunks": rows}, indent=2, default=str),
            "count": len(rows),
        }
    return {
        "filename": "corpus-export.md",
        "media_type": "text/markdown",
        "content": render_markdown(rows),
        "count": len(rows),
    }


async def export_to_note(
    client: Any, session: AsyncSession, external_ids: Sequence[str], title: str | None = None
) -> list[dict[str, Any]]:
    """Push the chunks as one note per source notebook (``client.notes.create``)."""
    rows = await _export_rows(session, external_ids)
    by_notebook: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["notebook_id"]:
            by_notebook[row["notebook_id"]].append(row)
    if not by_notebook:
        raise ValueError("none of the selected chunks belongs to a notebook")
    created = []
    for notebook_id, items in by_notebook.items():
        note_title = title or f"Corpus excerpts ({len(items)})"
        note = await client.notes.create(
            notebook_id, note_title, render_markdown(items, heading=note_title)
        )
        created.append(
            {"notebook_id": notebook_id, "note_id": getattr(note, "id", None), "count": len(items)}
        )
    return created
