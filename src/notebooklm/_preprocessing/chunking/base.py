"""Shared types for chunking strategies.

A strategy turns one document's text into parents (large context units) that
each hold children (the units that get embedded, tagged, and fact-checked).
Offsets are character offsets into the original text, so every stored chunk can
be traced back to the exact span it came from.

Invariants every strategy must keep:

* ``parent.text == text[parent.char_start:parent.char_end]``
* ``child.text == text[child.char_start:child.char_end]``
* children lie inside their parent and do not overlap; order follows the text
* no child is empty or whitespace-only
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class ChildChunk:
    text: str
    char_start: int
    char_end: int
    #: Optional precomputed embedding (cluster-semantic reuses sentence vectors
    #: so ingest does not embed twice). ``None`` means ingest must embed it.
    vector: list[float] | None = None


@dataclass
class ParentChunk:
    text: str
    char_start: int
    char_end: int
    children: list[ChildChunk] = field(default_factory=list)


@dataclass
class ChunkStats:
    """Counters a strategy accumulates during one ``chunk`` call."""

    #: Split candidates rejected because they fell inside a named-entity span.
    entity_vetoes: int = 0
    #: Free-form extras recorded into ``chunk_runs.params`` (e.g. ``fallback``).
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChunkResult:
    parents: list[ParentChunk]
    stats: ChunkStats = field(default_factory=ChunkStats)


@runtime_checkable
class ChunkStrategy(Protocol):
    #: Registry name stored in ``chunk_runs.strategy``.
    name: str
    #: Bumped whenever output for the same input can change; ``chunk_runs.chunker_version``.
    version: str

    @property
    def params(self) -> dict[str, Any]:
        """Parameters stored in ``chunk_runs.params``."""
        ...

    def chunk(self, text: str) -> ChunkResult: ...
