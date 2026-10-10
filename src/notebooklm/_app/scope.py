"""Which chunks an assessment (SFL tagging, fact-check) runs over.

The TUI scopes by notebook (optionally one parent). The web Corpus Explorer
also scopes by documents, runs, or an explicit chunk selection, so assessment
works on any corpus document: sources, notes and ingested artifacts alike.

Explicit ``run_ids`` / ``external_ids`` select exactly those rows; every other
scope reads only each document's *active* run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select

from ..db.models import ChunkRun, Clause


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(v for v in value.split(",") if v)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


@dataclass(frozen=True)
class Scope:
    notebook_id: str | None = None
    document_ids: tuple[str, ...] = ()
    run_ids: tuple[int, ...] = ()
    external_ids: tuple[str, ...] = ()
    parent_id: int | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> Scope:
        data = data or {}
        parent = data.get("parent_id")
        return cls(
            notebook_id=data.get("notebook_id") or None,
            document_ids=tuple(str(v) for v in _tuple(data.get("document_ids"))),
            run_ids=tuple(int(v) for v in _tuple(data.get("run_ids"))),
            external_ids=tuple(str(v) for v in _tuple(data.get("external_ids"))),
            parent_id=int(parent) if parent is not None else None,
        )

    @property
    def is_empty(self) -> bool:
        return not (
            self.notebook_id
            or self.document_ids
            or self.run_ids
            or self.external_ids
            or self.parent_id is not None
        )

    @property
    def explicit(self) -> bool:
        """Explicit run/chunk scopes may include inactive runs."""
        return bool(self.run_ids or self.external_ids)

    def apply(self, stmt: Select[Any]) -> Select[Any]:
        """Narrow a statement that already joins ``Clause`` and ``ChunkRun``."""
        if not self.explicit:
            stmt = stmt.where(ChunkRun.is_active.is_(True))
        if self.notebook_id:
            stmt = stmt.where(ChunkRun.notebook_id == self.notebook_id)
        if self.document_ids:
            stmt = stmt.where(Clause.document_id.in_(self.document_ids))
        if self.run_ids:
            stmt = stmt.where(Clause.run_id.in_(self.run_ids))
        if self.external_ids:
            stmt = stmt.where(Clause.external_id.in_(self.external_ids))
        if self.parent_id is not None:
            stmt = stmt.where(Clause.parent_id == self.parent_id)
        return stmt

    def describe(self) -> str:
        parts = []
        if self.notebook_id:
            parts.append(f"notebook {self.notebook_id}")
        if self.document_ids:
            parts.append(f"{len(self.document_ids)} document(s)")
        if self.run_ids:
            parts.append(f"{len(self.run_ids)} run(s)")
        if self.external_ids:
            parts.append(f"{len(self.external_ids)} chunk(s)")
        if self.parent_id is not None:
            parts.append(f"parent {self.parent_id}")
        return ", ".join(parts) or "whole corpus"

    def to_dict(self) -> dict[str, Any]:
        return {
            "notebook_id": self.notebook_id,
            "document_ids": list(self.document_ids),
            "run_ids": list(self.run_ids),
            "external_ids": list(self.external_ids),
            "parent_id": self.parent_id,
        }
