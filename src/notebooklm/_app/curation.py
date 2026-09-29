"""Curation business logic: remove items, add sources, delete notebooks.

Transport-neutral orchestration shared by the TUI (and any future adapter).
Never imports ``tui`` / ``click`` / ``rich`` (see
``tests/_guardrails/test_app_boundary.py``). Every removal is logged to the
local ``removal_log`` table; local clauses/embeddings are never purged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm.db.models import RemovalLog

#: Fixed set of reasons a removal must be attributed to (fact 3).
REMOVAL_REASONS = ("redundant", "incorrect", "experimental", "hallucinated", "other")

#: Item kinds understood by :func:`execute_remove_items`.
ITEM_KIND_SOURCE = "source"
ITEM_KIND_ARTIFACT = "artifact"
ITEM_KIND_NOTE = "note"
ITEM_KIND_MIND_MAP = "mind_map"


@dataclass
class CurationItem:
    """One removable thing in a notebook, with a stable kind tag."""

    kind: str
    id: str
    title: str

    def __post_init__(self) -> None:
        self.title = self.title or self.id


@dataclass
class RemovalResult:
    """Outcome of one batch removal (fact 5)."""

    removed: list[CurationItem] = field(default_factory=list)
    failed: list[tuple[CurationItem, str]] = field(default_factory=list)


async def list_curation_items(client: Any, notebook_id: str) -> list[CurationItem]:
    """List every removable item: sources, artifacts, notes, and mind maps.

    Interactive mind maps already appear in ``artifacts.list``; the note-backed
    kind does not, so it is fetched separately via ``mind_maps`` and removed
    through ``notes.delete_mind_map``.
    """
    sources = await client.sources.list(notebook_id)
    artifacts = await client.artifacts.list(notebook_id)
    notes = await client.notes.list(notebook_id)
    try:
        mind_maps = await client.mind_maps.list_note_backed(notebook_id)
    except Exception:
        mind_maps = []

    items: list[CurationItem] = []
    for src in sources:
        items.append(CurationItem(ITEM_KIND_SOURCE, src.id, getattr(src, "title", None) or src.id))
    for artifact in artifacts:
        items.append(
            CurationItem(
                ITEM_KIND_ARTIFACT, artifact.id, getattr(artifact, "title", None) or artifact.id
            )
        )
    for note in notes:
        items.append(CurationItem(ITEM_KIND_NOTE, note.id, getattr(note, "title", None) or note.id))
    for mind_map in mind_maps:
        items.append(
            CurationItem(
                ITEM_KIND_MIND_MAP, mind_map.id, getattr(mind_map, "title", None) or mind_map.id
            )
        )
    return items


def validate_add_source(kind: str, value: str) -> str | None:
    """Validate an add-source input without touching the network.

    Returns the validated value, or ``None`` when the input is invalid — the
    caller must show an error and make no request (fact 7).
    """
    value = value.strip()
    if kind == "url":
        if value and (value.startswith("http://") or value.startswith("https://")):
            return value
        return None
    if kind == "file":
        if value and Path(value).is_file():
            return value
        return None
    if kind == "text":
        return value or None
    return None


async def execute_add_source(
    client: Any,
    notebook_id: str,
    kind: str,
    value: str,
    *,
    title: str | None = None,
) -> Any:
    """Add a source by kind: URL (incl. YouTube), local file, or pasted text.

    ``add_url`` already routes YouTube URLs internally; no separate dispatch is
    needed for them.
    """
    if kind == "url":
        return await client.sources.add_url(notebook_id, value)
    if kind == "file":
        return await client.sources.add_file(notebook_id, value)
    if kind == "text":
        return await client.sources.add_text(notebook_id, title or "Pasted text", value)
    raise ValueError(f"Unknown add-source kind: {kind!r}")


def title_confirmation_matches(title: str, typed: str) -> bool:
    """Case-insensitive prefix match used for destructive confirmations.

    The typed text must be a prefix of the title and at least
    ``min(len(title), 4)`` characters long.
    """
    typed = typed.strip()
    if not typed:
        return False
    if len(typed) < min(len(title), 4):
        return False
    return title.lower().startswith(typed.lower())


async def execute_remove_items(
    client: Any,
    session: AsyncSession,
    notebook_id: str,
    notebook_title: str,
    items: list[CurationItem],
    reason: str,
) -> RemovalResult:
    """Remove a batch of items, logging each success to ``removal_log``.

    Raises ``ValueError`` before any network call when ``reason`` is not in
    :data:`REMOVAL_REASONS`. Individual failures are collected and the batch
    continues (fact 5); only successful removals are logged.
    """
    if reason not in REMOVAL_REASONS:
        raise ValueError(f"reason must be one of {REMOVAL_REASONS}, got {reason!r}")

    result = RemovalResult()
    for item in items:
        try:
            if item.kind == ITEM_KIND_SOURCE:
                await client.sources.delete(notebook_id, item.id)
            elif item.kind == ITEM_KIND_ARTIFACT:
                await client.artifacts.delete(notebook_id, item.id)
            elif item.kind == ITEM_KIND_NOTE:
                await client.notes.delete(notebook_id, item.id)
            elif item.kind == ITEM_KIND_MIND_MAP:
                await client.notes.delete_mind_map(notebook_id, item.id)
            else:
                raise ValueError(f"Unknown item kind: {item.kind!r}")
        except Exception as exc:  # noqa: BLE001 — one bad item must not abort the batch
            result.failed.append((item, str(exc)))
            continue
        result.removed.append(item)
        session.add(
            RemovalLog(
                notebook_id=notebook_id,
                notebook_title=notebook_title,
                item_id=item.id,
                item_title=item.title,
                item_type=item.kind,
                action="remove",
                reason=reason,
            )
        )
    if result.removed:
        await session.commit()
    return result


async def execute_delete_notebook(
    client: Any,
    session: AsyncSession,
    notebook_id: str,
    notebook_title: str,
    reason: str,
) -> None:
    """Delete the remote notebook and log the removal locally."""
    if reason not in REMOVAL_REASONS:
        raise ValueError(f"reason must be one of {REMOVAL_REASONS}, got {reason!r}")
    await client.notebooks.delete(notebook_id)
    session.add(
        RemovalLog(
            notebook_id=notebook_id,
            notebook_title=notebook_title,
            item_id=notebook_id,
            item_title=notebook_title,
            item_type="notebook",
            action="delete_notebook",
            reason=reason,
        )
    )
    await session.commit()
