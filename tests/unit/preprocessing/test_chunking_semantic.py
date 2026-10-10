"""Tests for the cluster-semantic chunker, using injected embedder and sentence splitter."""

from __future__ import annotations

import re

import numpy as np
import pytest

from notebooklm._preprocessing.chunking.base import ChunkResult, ChunkStrategy
from notebooklm._preprocessing.chunking.semantic import ClusterSemanticChunker

BASIS = {0: [1.0, 0.0, 0.0], 1: [0.0, 1.0, 0.0], 2: [0.0, 0.0, 1.0]}
SENTENCES = [f"Sentence number {i} talks about topic {'ABC'[i // 3]}." for i in range(9)]
TEXT = " ".join(SENTENCES)


def _cluster_of(sentence: str) -> int:
    return int(sentence.split()[2]) // 3


def _fake_embed(texts: list[str]) -> list[list[float]]:
    return [BASIS[_cluster_of(t)] for t in texts]


def _sentence_spans_of(text: str) -> list[tuple[int, int]]:
    spans = []
    pos = 0
    for sentence in SENTENCES:
        start = text.index(sentence, pos)
        spans.append((start, start + len(sentence)))
        pos = start + len(sentence)
    return spans


def _regex_sentence_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"[^.!?]+[.!?]", text)]


def _assert_invariants(text: str, result: ChunkResult) -> None:
    prev_parent_end = 0
    for parent in result.parents:
        assert parent.text == text[parent.char_start : parent.char_end]
        assert parent.char_start >= prev_parent_end
        prev_parent_end = parent.char_end
        prev_end = parent.char_start
        for child in parent.children:
            assert child.text == text[child.char_start : child.char_end]
            assert child.text.strip()
            assert parent.char_start <= child.char_start < child.char_end <= parent.char_end
            assert child.char_start >= prev_end
            prev_end = child.char_end


def test_breaks_land_at_embedding_jumps():
    chunker = ClusterSemanticChunker(
        min_child_chars=1,
        embed=_fake_embed,
        sentence_spans=_sentence_spans_of,
    )
    result = chunker.chunk(TEXT)

    assert len(result.parents) == 1
    children = result.parents[0].children
    assert [c.text for c in children] == [
        " ".join(SENTENCES[0:3]),
        " ".join(SENTENCES[3:6]),
        " ".join(SENTENCES[6:9]),
    ]
    assert result.stats.extra["threshold"] == pytest.approx(1.0)
    _assert_invariants(TEXT, result)


def test_children_carry_normalized_mean_vectors():
    chunker = ClusterSemanticChunker(
        min_child_chars=1,
        embed=_fake_embed,
        sentence_spans=_sentence_spans_of,
    )
    children = chunker.chunk(TEXT).parents[0].children

    expected = [BASIS[0], BASIS[1], BASIS[2]]
    for child, vector in zip(children, expected, strict=True):
        assert child.vector is not None
        assert np.allclose(child.vector, vector)
        assert np.linalg.norm(child.vector) == pytest.approx(1.0)


def test_small_groups_merge_into_neighbours():
    chunker = ClusterSemanticChunker(
        min_child_chars=1_000,
        max_child_chars=10_000,
        embed=_fake_embed,
        sentence_spans=_sentence_spans_of,
    )
    children = chunker.chunk(TEXT).parents[0].children

    assert len(children) == 1
    assert children[0].text == TEXT


def test_oversize_groups_split_at_sentence_boundaries():
    chunker = ClusterSemanticChunker(
        min_child_chars=1,
        max_child_chars=100,
        embed=lambda texts: [BASIS[0] for _ in texts],
        sentence_spans=_sentence_spans_of,
    )
    result = chunker.chunk(TEXT)
    children = result.parents[0].children

    assert len(children) > 1
    assert all(len(c.text) <= 100 for c in children)
    assert all(c.text.endswith(".") for c in children)
    assert result.stats.extra["threshold"] == pytest.approx(0.0)
    _assert_invariants(TEXT, result)


def test_oversize_single_sentence_is_windowed_and_keeps_vector():
    run_on = "word " * 40 + "end."
    chunker = ClusterSemanticChunker(
        min_child_chars=1,
        max_child_chars=60,
        embed=lambda texts: [BASIS[1] for _ in texts],
        sentence_spans=_regex_sentence_spans,
    )
    result = chunker.chunk(run_on)
    children = result.parents[0].children

    assert len(children) > 1
    assert all(len(c.text) <= 60 for c in children)
    assert all(np.allclose(c.vector, BASIS[1]) for c in children)
    _assert_invariants(run_on, result)


def test_multi_paragraph_text_with_default_parent_packing():
    text = (
        "First paragraph one. First paragraph two.\n\n"
        "Second paragraph here. It keeps going.\n\n"
        + "Long run without any stop " * 12
        + "end.\n\nTail paragraph."
    )
    chunker = ClusterSemanticChunker(
        min_child_chars=1,
        max_child_chars=120,
        parent_max_chars=150,
        embed=lambda texts: [BASIS[i % 3] for i in range(len(texts))],
        sentence_spans=_regex_sentence_spans,
    )
    result = chunker.chunk(text)

    assert len(result.parents) > 1
    assert all(len(c.text) <= 120 for p in result.parents for c in p.children)
    _assert_invariants(text, result)


def test_single_sentence_parent():
    chunker = ClusterSemanticChunker(
        embed=lambda texts: [[3.0, 4.0] for _ in texts],
        sentence_spans=_regex_sentence_spans,
    )
    text = "Only one sentence here."
    result = chunker.chunk(text)

    assert len(result.parents) == 1
    children = result.parents[0].children
    assert len(children) == 1
    assert children[0].text == text
    assert children[0].vector == pytest.approx([0.6, 0.8])
    assert result.stats.extra["threshold"] is None
    _assert_invariants(text, result)


def test_empty_text_yields_no_parents():
    chunker = ClusterSemanticChunker(embed=_fake_embed, sentence_spans=_sentence_spans_of)
    result = chunker.chunk("   \n\n  ")

    assert result.parents == []
    assert result.stats.extra["threshold"] is None


def test_satisfies_chunk_strategy_protocol():
    chunker = ClusterSemanticChunker(embed=_fake_embed, sentence_spans=_sentence_spans_of)

    assert isinstance(chunker, ChunkStrategy)
    assert chunker.name == "cluster_semantic"
    assert chunker.version == "1"
    assert chunker.params["percentile"] == 90.0


def test_rejects_inconsistent_size_bounds():
    with pytest.raises(ValueError):
        ClusterSemanticChunker(min_child_chars=500, max_child_chars=100)
    with pytest.raises(ValueError):
        ClusterSemanticChunker(percentile=101.0)
