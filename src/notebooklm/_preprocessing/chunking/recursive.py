"""Recursive splitter: parents and children from a separator ladder with an entity guard.

Parents pack blank-line, newline and whitespace pieces up to ``parent_max_chars``.
Children apply the ladder inside each parent: blank line, newline, sentence
punctuation, spaCy sentence boundary, whitespace, then a hard character cut. A
level only touches pieces that are still over ``child_max_chars``. A candidate
split offset strictly inside a named entity that fits the limit is rejected and
counted in ``ChunkStats.entity_vetoes``.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

from .base import ChildChunk, ChunkResult, ChunkStats, ParentChunk

Span = tuple[int, int]
#: Removed separators as (start, end). A point cut has start == end.
Cuts = list[Span]
Level = Callable[[Span], Cuts]

SPACY_MODEL = "en_core_web_md"
_BLANK_LINE = re.compile(r"\n\s*\n")
_NEWLINE = re.compile(r"\n")
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+")
_WHITESPACE = re.compile(r"\s+")


@lru_cache(maxsize=1)
def load_spacy(model: str = SPACY_MODEL) -> Any:
    """Load the spaCy pipeline once per process."""
    import spacy

    return spacy.load(model)


class EntityGuard:
    """Rejects cuts strictly inside a named entity no longer than ``limit``."""

    def __init__(self, entities: Callable[[], list[Span]], limit: float, stats: ChunkStats) -> None:
        self._entities = entities
        self._limit = limit
        self._stats = stats
        self._spans: list[Span] | None = None

    def keep(self, cut_start: int, cut_end: int) -> bool:
        if self._spans is None:
            self._spans = self._entities()
        for offset in (cut_start, cut_end):
            for ent_start, ent_end in self._spans:
                if ent_start < offset < ent_end and ent_end - ent_start <= self._limit:
                    self._stats.entity_vetoes += 1
                    return False
        return True


class _Parse:
    """One spaCy parse of a span, shared by the entity guard and the sentence level."""

    def __init__(
        self,
        text: str,
        span: Span,
        model: Callable[[], Any],
        use_entities: bool,
    ) -> None:
        self._text = text
        self._span = span
        self._model = model
        self._use_entities = use_entities
        self._doc: Any = None
        self._starts: list[int] | None = None

    def _parse(self) -> Any:
        if self._doc is None:
            start, end = self._span
            self._doc = self._model()(self._text[start:end])
        return self._doc

    def entities(self) -> list[Span]:
        if not self._use_entities:
            return []
        offset, _ = self._span
        return [(offset + ent.start_char, offset + ent.end_char) for ent in self._parse().ents]

    def sentence_starts(self) -> list[int]:
        if self._starts is None:
            offset, _ = self._span
            self._starts = [offset + sent.start_char for sent in self._parse().sents]
        return self._starts


def _regex_level(pattern: re.Pattern[str], text: str, guard: EntityGuard) -> Level:
    def level(span: Span) -> Cuts:
        start, end = span
        return [
            (m.start(), m.end())
            for m in pattern.finditer(text, start, end)
            if guard.keep(m.start(), m.end())
        ]

    return level


def _sentence_level(scope: _Parse, guard: EntityGuard) -> Level:
    def level(span: Span) -> Cuts:
        start, end = span
        return [(x, x) for x in scope.sentence_starts() if start < x < end and guard.keep(x, x)]

    return level


def _pieces(span: Span, cuts: Cuts) -> list[Span]:
    """Return the non-empty pieces of ``span`` between ``cuts``."""
    start, end = span
    out: list[Span] = []
    prev = start
    for cut_start, cut_end in cuts:
        if cut_start > prev:
            out.append((prev, cut_start))
        prev = max(prev, cut_end)
    if end > prev:
        out.append((prev, end))
    return out


def _hard_cut(span: Span, limit: int, guard: EntityGuard) -> list[Span]:
    """Cut at ``limit`` characters, moving back to the nearest permitted offset."""
    start, end = span
    out: list[Span] = []
    while end - start > limit:
        cut = next(
            (c for c in range(start + limit, start, -1) if guard.keep(c, c)),
            start + limit,
        )
        out.append((start, cut))
        start = cut
    out.append((start, end))
    return out


def _split(span: Span, levels: Sequence[Level], limit: int, guard: EntityGuard) -> list[Span]:
    """Split ``span`` into pieces of at most ``limit`` characters, one ladder level at a time."""
    start, end = span
    if end - start <= limit:
        return [span]
    if not levels:
        return _hard_cut(span, limit, guard)
    head, *rest = levels
    out: list[Span] = []
    current: Span | None = None
    for piece in _pieces(span, head(span)):
        piece_start, piece_end = piece
        if piece_end - piece_start > limit:
            if current is not None:
                out.append(current)
                current = None
            out.extend(_split(piece, rest, limit, guard))
            continue
        if current is not None:
            current_start, _ = current
            if piece_end - current_start <= limit:
                current = (current_start, piece_end)
                continue
        if current is not None:
            out.append(current)
        current = piece
    if current is not None:
        out.append(current)
    return out


def _clean(text: str, spans: Sequence[Span]) -> list[Span]:
    """Strip surrounding whitespace from each span and drop spans left empty."""
    out: list[Span] = []
    for start, end in spans:
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            out.append((start, end))
    return out


class RecursiveSplitter:
    """Parent and child spans from a separator ladder. Implements ``ChunkStrategy``."""

    name = "recursive"
    version = "1"

    def __init__(
        self,
        parent_max_chars: int = 4000,
        child_max_chars: int = 512,
        nlp: Any | None = None,
        use_entity_guard: bool = True,
    ) -> None:
        if child_max_chars < 1 or parent_max_chars < child_max_chars:
            raise ValueError("require 1 <= child_max_chars <= parent_max_chars")
        self.parent_max_chars = parent_max_chars
        self.child_max_chars = child_max_chars
        self.use_entity_guard = use_entity_guard
        self._nlp = nlp

    @property
    def params(self) -> dict[str, Any]:
        return {
            "parent_max_chars": self.parent_max_chars,
            "child_max_chars": self.child_max_chars,
            "use_entity_guard": self.use_entity_guard,
            "spacy_model": SPACY_MODEL,
        }

    def chunk(self, text: str) -> ChunkResult:
        stats = ChunkStats()
        parents: list[ParentChunk] = []
        for start, end in self._parent_spans(text):
            children = [
                ChildChunk(text[s:e], s, e) for s, e in self._child_spans(text, (start, end), stats)
            ]
            parents.append(ParentChunk(text[start:end], start, end, children))
        return ChunkResult(parents=parents, stats=stats)

    def split_sentences(self, text: str) -> list[tuple[int, int]]:
        """Sentence spans from the ladder with no size limit. Entity-internal cuts are skipped."""
        if not text.strip():
            return []
        scope = _Parse(text, (0, len(text)), self._model, self.use_entity_guard)
        guard = EntityGuard(scope.entities, math.inf, ChunkStats())
        levels: list[Level] = [
            _regex_level(_BLANK_LINE, text, guard),
            _regex_level(_NEWLINE, text, guard),
            _regex_level(_SENTENCE_END, text, guard),
            _sentence_level(scope, guard),
        ]
        spans = [(0, len(text))]
        for level in levels:
            spans = [piece for span in spans for piece in _pieces(span, level(span))]
        return _clean(text, spans)

    def _model(self) -> Any:
        if self._nlp is None:
            self._nlp = load_spacy(SPACY_MODEL)
        return self._nlp

    def _parent_spans(self, text: str) -> list[Span]:
        # Parent packing does not consult entities; the guard only applies to children.
        guard = EntityGuard(lambda: [], self.parent_max_chars, ChunkStats())
        levels: list[Level] = [
            _regex_level(_BLANK_LINE, text, guard),
            _regex_level(_NEWLINE, text, guard),
            _regex_level(_WHITESPACE, text, guard),
        ]
        return _clean(text, _split((0, len(text)), levels, self.parent_max_chars, guard))

    def _child_spans(self, text: str, parent: Span, stats: ChunkStats) -> list[Span]:
        parent_start, parent_end = parent
        if parent_end - parent_start <= self.child_max_chars:
            return [parent]
        scope = _Parse(text, parent, self._model, self.use_entity_guard)
        guard = EntityGuard(scope.entities, self.child_max_chars, stats)
        levels: list[Level] = [
            _regex_level(_BLANK_LINE, text, guard),
            _regex_level(_NEWLINE, text, guard),
            _regex_level(_SENTENCE_END, text, guard),
            _sentence_level(scope, guard),
            _regex_level(_WHITESPACE, text, guard),
        ]
        return _clean(text, _split(parent, levels, self.child_max_chars, guard))


__all__ = ["EntityGuard", "RecursiveSplitter", "load_spacy"]
