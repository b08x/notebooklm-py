"""Cluster-semantic chunker: breaks each parent where adjacent sentence embeddings diverge.

Sentences are embedded once. The cosine distance between neighbours is computed
across the whole document, and the document's ``percentile`` distance sets the
break threshold. Groups below ``min_child_chars`` merge into a neighbour, and
groups above ``max_child_chars`` split at sentence boundaries. Each child carries
the normalized mean of its sentence vectors, so ingest does not embed it again.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable
from typing import Any

import numpy as np

from ..embeddings import OllamaEmbeddingAdapter
from .base import ChildChunk, ChunkResult, ChunkStats, ParentChunk

Span = tuple[int, int]
Embedder = Callable[[list[str]], list[list[float]]]
Splitter = Callable[[str], list[Span]]

_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _trim(text: str, start: int, end: int) -> Span | None:
    """Return the span with surrounding whitespace removed, or None if it is empty."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


def _window_spans(text: str, start: int, end: int, max_chars: int) -> list[Span]:
    """Cut ``[start, end)`` into pieces of at most ``max_chars``, preferring whitespace."""
    spans: list[Span] = []
    pos = start
    while end - pos > max_chars:
        window = text[pos : pos + max_chars + 1]
        cut = max((i for i, ch in enumerate(window) if i > 0 and ch.isspace()), default=max_chars)
        piece = _trim(text, pos, pos + cut)
        if piece:
            spans.append(piece)
        pos += cut
        while pos < end and text[pos].isspace():
            pos += 1
    tail = _trim(text, pos, end)
    if tail:
        spans.append(tail)
    return spans


def _paragraph_spans(text: str, max_chars: int) -> list[Span]:
    """Split on blank lines, pack paragraphs up to ``max_chars``, window any oversize one."""
    blocks: list[Span] = []
    start = 0
    for match in _PARAGRAPH_BREAK.finditer(text):
        block = _trim(text, start, match.start())
        if block:
            blocks.append(block)
        start = match.end()
    last = _trim(text, start, len(text))
    if last:
        blocks.append(last)

    packed: list[Span] = []
    current: Span | None = None
    for s, e in blocks:
        if e - s > max_chars:
            if current:
                packed.append(current)
                current = None
            packed.extend(_window_spans(text, s, e, max_chars))
        elif current and e - current[0] <= max_chars:
            current = (current[0], e)
        else:
            if current:
                packed.append(current)
            current = (s, e)
    if current:
        packed.append(current)
    return packed


def _adjacent_distances(vectors: np.ndarray) -> np.ndarray:
    """Cosine distance between each sentence vector and the next (rows are unit length)."""
    return 1.0 - np.sum(vectors[:-1] * vectors[1:], axis=1)


def _unit_rows(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _span_len(sents: list[Span], lo: int, hi: int) -> int:
    return sents[hi - 1][1] - sents[lo][0]


def _break_groups(n: int, distances: np.ndarray, threshold: float | None) -> list[tuple[int, int]]:
    """Group sentence indices ``[lo, hi)``; break after neighbours at or above the threshold."""
    groups: list[tuple[int, int]] = []
    start = 0
    if threshold is not None:
        for i, distance in enumerate(distances):
            if distance >= threshold and distance > 0.0:
                groups.append((start, i + 1))
                start = i + 1
    groups.append((start, n))
    return groups


def _merge_small(
    groups: list[tuple[int, int]], sents: list[Span], min_chars: int
) -> list[tuple[int, int]]:
    """Merge each group under ``min_chars`` into its smaller neighbour until none remain."""
    groups = list(groups)
    while len(groups) > 1:
        idx = next(
            (i for i, (lo, hi) in enumerate(groups) if _span_len(sents, lo, hi) < min_chars),
            None,
        )
        if idx is None:
            break
        neighbours = [j for j in (idx - 1, idx + 1) if 0 <= j < len(groups)]
        j = min(neighbours, key=lambda k: _span_len(sents, *groups[k]))
        merged = (min(groups[idx][0], groups[j][0]), max(groups[idx][1], groups[j][1]))
        groups[min(idx, j)] = merged
        del groups[max(idx, j)]
    return groups


def _pack(sents: list[Span], lo: int, hi: int, max_chars: int) -> list[tuple[int, int]]:
    """Greedily pack sentences ``[lo, hi)`` into pieces no longer than ``max_chars``."""
    pieces: list[tuple[int, int]] = []
    start = lo
    for k in range(lo + 1, hi):
        if sents[k][1] - sents[start][0] > max_chars:
            pieces.append((start, k))
            start = k
    pieces.append((start, hi))
    return pieces


def _mean_vector(vectors: np.ndarray, lo: int, hi: int) -> list[float]:
    mean = vectors[lo:hi].mean(axis=0)
    return _unit_rows(mean[np.newaxis, :])[0].tolist()


class ClusterSemanticChunker:
    """Breaks each parent at embedding discontinuities between adjacent sentences."""

    name = "cluster_semantic"
    version = "1"

    def __init__(
        self,
        percentile: float = 90.0,
        min_child_chars: int = 200,
        max_child_chars: int = 1200,
        parent_max_chars: int = 4000,
        embed: Embedder | None = None,
        sentence_spans: Splitter | None = None,
        parent_spans: Splitter | None = None,
    ) -> None:
        if not 0.0 <= percentile <= 100.0:
            raise ValueError(f"percentile must be in [0, 100], got {percentile}")
        if not 0 <= min_child_chars <= max_child_chars or max_child_chars < 1:
            raise ValueError(
                f"need 0 <= min_child_chars <= max_child_chars, got {min_child_chars}, "
                f"{max_child_chars}"
            )
        if parent_max_chars < 1:
            raise ValueError(f"parent_max_chars must be >= 1, got {parent_max_chars}")
        self.percentile = percentile
        self.min_child_chars = min_child_chars
        self.max_child_chars = max_child_chars
        self.parent_max_chars = parent_max_chars
        self._embed = embed
        self._sentence_spans = sentence_spans
        self._parent_spans = parent_spans

    @property
    def params(self) -> dict[str, Any]:
        return {
            "percentile": self.percentile,
            "min_child_chars": self.min_child_chars,
            "max_child_chars": self.max_child_chars,
            "parent_max_chars": self.parent_max_chars,
        }

    def chunk(self, text: str) -> ChunkResult:
        staged: list[tuple[int, int, list[Span], np.ndarray]] = []
        distances: list[np.ndarray] = []
        for ps, pe in self._parent_bounds(text):
            sents = self._sentences(text, ps, pe)
            vectors = self._embed_sentences(text, sents)
            if len(sents) > 1:
                distances.append(_adjacent_distances(vectors))
            staged.append((ps, pe, sents, vectors))

        all_distances = np.concatenate(distances) if distances else np.empty(0)
        threshold = (
            float(np.percentile(all_distances, self.percentile)) if all_distances.size else None
        )
        parents = [
            self._build_parent(text, ps, pe, sents, vectors, threshold)
            for ps, pe, sents, vectors in staged
        ]
        return ChunkResult(parents=parents, stats=ChunkStats(extra={"threshold": threshold}))

    def _build_parent(
        self,
        text: str,
        ps: int,
        pe: int,
        sents: list[Span],
        vectors: np.ndarray,
        threshold: float | None,
    ) -> ParentChunk:
        if not sents:
            spans = _window_spans(text, ps, pe, self.max_child_chars)
            children = [ChildChunk(text[s:e], s, e) for s, e in spans]
            return ParentChunk(text[ps:pe], ps, pe, children)

        distances = _adjacent_distances(vectors) if len(sents) > 1 else np.empty(0)
        groups = _break_groups(len(sents), distances, threshold)
        groups = _merge_small(groups, sents, self.min_child_chars)

        children = []
        for lo, hi in groups:
            for a, b in _pack(sents, lo, hi, self.max_child_chars):
                if b - a == 1 and _span_len(sents, a, b) > self.max_child_chars:
                    for s, e in _window_spans(text, sents[a][0], sents[a][1], self.max_child_chars):
                        children.append(ChildChunk(text[s:e], s, e, _mean_vector(vectors, a, b)))
                else:
                    s, e = sents[a][0], sents[b - 1][1]
                    children.append(ChildChunk(text[s:e], s, e, _mean_vector(vectors, a, b)))
        return ParentChunk(text[ps:pe], ps, pe, children)

    def _parent_bounds(self, text: str) -> list[Span]:
        if self._parent_spans is not None:
            raw = self._parent_spans(text)
        else:
            raw = _paragraph_spans(text, self.parent_max_chars)
        bounds: list[Span] = []
        for s, e in raw:
            trimmed = _trim(text, s, e)
            if trimmed:
                bounds.append(trimmed)
        return bounds

    def _sentences(self, text: str, ps: int, pe: int) -> list[Span]:
        """Sentence spans inside ``[ps, pe)``, as absolute offsets into ``text``."""
        if self._sentence_spans is None:
            module = importlib.import_module(f"{__package__}.recursive")
            self._sentence_spans = module.RecursiveSplitter().split_sentences
        sentence_spans = self._sentence_spans
        spans: list[Span] = []
        for s, e in sentence_spans(text[ps:pe]):
            trimmed = _trim(text, ps + max(s, 0), ps + min(e, pe - ps))
            if trimmed:
                spans.append(trimmed)
        return spans

    def _embed_sentences(self, text: str, sents: list[Span]) -> np.ndarray:
        if not sents:
            return np.empty((0, 0))
        if self._embed is None:
            self._embed = OllamaEmbeddingAdapter().embed
        raw = self._embed([text[s:e] for s, e in sents])
        if len(raw) != len(sents):
            raise ValueError(f"embedder returned {len(raw)} vectors for {len(sents)} sentences")
        return _unit_rows(np.asarray(raw, dtype=float))
