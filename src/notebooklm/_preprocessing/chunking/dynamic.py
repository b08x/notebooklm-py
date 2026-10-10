"""Dynamic-window chunker: a DSPy predictor proposes child boundaries per parent.

Each parent is a run of sentences. The predictor returns the sentence indices where
a new child starts. Invalid output, a predictor error, or a child over
``max_child_chars`` falls back to greedy sentence packing for that parent.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Any

import dspy

from .base import ChildChunk, ChunkResult, ChunkStats, ParentChunk

Span = tuple[int, int]
SpanFn = Callable[[str], Sequence[Span]]

_BLOCK_SEP = re.compile(r"\n\s*\n")
_SENTENCE_SEP = re.compile(r"(?<=[.?!])\s+")


class DynamicBoundsSignature(dspy.Signature):
    """Split consecutive sentences into child chunks at topic or argument shifts."""

    sentences: list[str] = dspy.InputField(desc="Consecutive sentences of one parent passage.")
    min_chars: int = dspy.InputField(desc="Preferred minimum characters per child.")
    max_chars: int = dspy.InputField(desc="Hard maximum characters per child.")
    boundaries: list[int] = dspy.OutputField(
        desc="Strictly increasing sentence indices where a new child starts, each in 1..len(sentences)-1."
    )


def _strip(text: str, start: int, end: int) -> Span | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if end > start else None


def _normalize(text: str, spans: Sequence[Span]) -> list[Span]:
    """Sort spans, clamp to the text, strip whitespace and drop overlaps."""
    out: list[Span] = []
    last_end = 0
    for start, end in sorted(spans):
        span = _strip(text, max(start, last_end), min(end, len(text)))
        if span is None:
            continue
        out.append(span)
        _, last_end = span
    return out


def _append_packed(out: list[Span], start: int, end: int, max_chars: int) -> None:
    """Append a span, merging it into the last span when the merge stays within ``max_chars``."""
    if out:
        head, tail = out.pop()
        if end - head <= max_chars:
            out.append((head, end))
            return
        out.append((head, tail))
    out.append((start, end))


def _pack(spans: Sequence[Span], max_chars: int) -> list[Span]:
    """Merge consecutive spans while the merged span stays within ``max_chars``."""
    out: list[Span] = []
    for start, end in spans:
        _append_packed(out, start, end, max_chars)
    return out


def _blocks(text: str) -> list[Span]:
    """Return the text spans between blank lines."""
    spans: list[Span] = []
    pos = 0
    for m in _BLOCK_SEP.finditer(text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def _default_parent_spans(text: str, max_chars: int) -> list[Span]:
    """Blank-line blocks packed to ``max_chars``; oversize blocks split at sentence ends."""
    units: list[Span] = []
    for start, end in _normalize(text, _blocks(text)):
        if end - start <= max_chars:
            units.append((start, end))
            continue
        pos = start
        for m in _SENTENCE_SEP.finditer(text, start, end):
            units.append((pos, m.start()))
            pos = m.end()
        units.append((pos, end))
    return _pack(_normalize(text, units), max_chars)


def _default_sentence_spans(text: str) -> list[Span]:
    from .recursive import RecursiveSplitter  # lazy: the recursive module loads spaCy

    return list(RecursiveSplitter().split_sentences(text))


def _hard_split(text: str, start: int, end: int, max_chars: int) -> list[Span]:
    """Cut one oversize span at whitespace where possible, otherwise at ``max_chars``."""
    out: list[Span] = []
    while end - start > max_chars:
        cut = start + max_chars
        for i in range(cut, start, -1):
            if text[i - 1].isspace():
                cut = i
                break
        piece = _strip(text, start, cut)
        if piece is not None:
            out.append(piece)
        start = cut
    tail = _strip(text, start, end)
    if tail is not None:
        out.append(tail)
    return out


def _greedy(text: str, sentences: Sequence[Span], max_chars: int) -> list[Span]:
    """Pack sentences into children up to ``max_chars``, hard-splitting oversize sentences."""
    out: list[Span] = []
    for start, end in sentences:
        if end - start > max_chars:
            out.extend(_hard_split(text, start, end, max_chars))
        else:
            _append_packed(out, start, end, max_chars)
    return out


def _valid_bounds(raw: Sequence[Any], n_sentences: int) -> list[int]:
    """Keep ints strictly increasing and inside (0, n_sentences); drop the rest."""
    kept: list[int] = []
    last = 0
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if not 0 < value < n_sentences or value <= last:
            continue
        kept.append(value)
        last = value
    return kept


class DynamicWindowChunker:
    """Chunk each parent into children at boundaries proposed by a DSPy predictor."""

    name = "dynamic_window"
    version = "1"

    def __init__(
        self,
        min_child_chars: int = 200,
        max_child_chars: int = 1200,
        parent_max_chars: int = 4000,
        predictor: Callable[..., Any] | None = None,
        sentence_spans: SpanFn | None = None,
        parent_spans: SpanFn | None = None,
    ) -> None:
        if not 0 < min_child_chars <= max_child_chars <= parent_max_chars:
            raise ValueError("require 0 < min_child_chars <= max_child_chars <= parent_max_chars")
        self.min_child_chars = min_child_chars
        self.max_child_chars = max_child_chars
        self.parent_max_chars = parent_max_chars
        self._predictor: Callable[..., Any] = (
            predictor if predictor is not None else dspy.ChainOfThought(DynamicBoundsSignature)
        )
        self._sentence_spans: SpanFn = (
            sentence_spans if sentence_spans is not None else _default_sentence_spans
        )
        self._parent_spans = parent_spans

    @property
    def params(self) -> dict[str, Any]:
        return {
            "min_child_chars": self.min_child_chars,
            "max_child_chars": self.max_child_chars,
            "parent_max_chars": self.parent_max_chars,
        }

    def chunk(self, text: str) -> ChunkResult:
        stats = ChunkStats()
        sentences = _normalize(text, self._sentence_spans(text))
        if self._parent_spans is None:
            parent_spans = _default_parent_spans(text, self.parent_max_chars)
        else:
            parent_spans = _normalize(text, self._parent_spans(text))

        parents: list[ParentChunk] = []
        fallbacks = 0
        for p_start, p_end in parent_spans:
            sub = _normalize(
                text, [(s, min(e, p_end)) for s, e in sentences if p_start <= s < p_end]
            )
            if not sub:
                continue
            child_spans, fell_back = self._children(text, sub)
            fallbacks += fell_back
            parents.append(
                ParentChunk(
                    text=text[p_start:p_end],
                    char_start=p_start,
                    char_end=p_end,
                    children=[
                        ChildChunk(text=text[s:e], char_start=s, char_end=e) for s, e in child_spans
                    ],
                )
            )

        stats.extra["fallback"] = fallbacks > 0
        stats.extra["fallback_count"] = fallbacks
        return ChunkResult(parents=parents, stats=stats)

    def _children(self, text: str, sub: list[Span]) -> tuple[list[Span], bool]:
        """Return child spans for one parent and whether the fallback was used."""
        if len(sub) == 1 and all(e - s <= self.max_child_chars for s, e in sub):
            return sub, False
        if len(sub) > 1:
            proposed = self._propose(text, sub)
            if proposed is not None:
                return proposed, False
        return _greedy(text, sub, self.max_child_chars), True

    def _propose(self, text: str, sub: list[Span]) -> list[Span] | None:
        """Ask the predictor for boundaries; ``None`` when the output is unusable."""
        try:
            raw = self._predictor(
                sentences=[text[s:e] for s, e in sub],
                min_chars=self.min_child_chars,
                max_chars=self.max_child_chars,
            ).boundaries
        except Exception:
            return None
        if not isinstance(raw, (list, tuple)):
            return None
        cuts = [0, *_valid_bounds(raw, len(sub)), len(sub)]
        spans = [(sub[a][0], sub[b - 1][1]) for a, b in pairwise(cuts)]
        if any(end - start > self.max_child_chars for start, end in spans):
            return None
        return spans
