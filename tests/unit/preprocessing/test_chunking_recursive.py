"""Tests for the recursive parent/child splitter."""

from __future__ import annotations

from types import SimpleNamespace

from notebooklm._preprocessing.chunking import make_strategy
from notebooklm._preprocessing.chunking.base import ChunkResult, ChunkStrategy
from notebooklm._preprocessing.chunking.recursive import RecursiveSplitter

FIXTURE = (
    "Introduction paragraph with two sentences. It sets the scene.\n\n"
    "- first list item\n- second list item\n- third list item\n\n"
    + "A very long sentence "
    + "that keeps going and going " * 20
    + "ends here.\n\n"
    + "x" * 900
    + "\n\n"
    + "The New York Times reported on Monday. Analysts disagreed.\n\n"
)


def _assert_invariants(text: str, result: ChunkResult) -> None:
    prev_parent_end = 0
    for parent in result.parents:
        assert parent.text == text[parent.char_start : parent.char_end]
        assert parent.text.strip(), "parent must not be empty"
        assert parent.char_start >= prev_parent_end, "parents must be ordered and disjoint"
        prev_parent_end = parent.char_end
        assert parent.children, "every non-empty parent holds at least one child"
        prev_child_end = parent.char_start
        for child in parent.children:
            assert child.text == text[child.char_start : child.char_end]
            assert child.text.strip(), "child must not be whitespace-only"
            assert parent.char_start <= child.char_start < child.char_end <= parent.char_end
            assert child.char_start >= prev_child_end, "children must be ordered and disjoint"
            prev_child_end = child.char_end


def _child_texts(result: ChunkResult) -> list[str]:
    return [child.text for parent in result.parents for child in parent.children]


def test_chunk_strategy_protocol_and_registry():
    splitter = RecursiveSplitter()
    assert isinstance(splitter, ChunkStrategy)
    assert splitter.name == "recursive"
    assert splitter.version == "1"
    assert splitter.params["child_max_chars"] == 512
    assert splitter.params["parent_max_chars"] == 4000
    assert isinstance(make_strategy("recursive", child_max_chars=100), RecursiveSplitter)


def test_invariants_on_varied_fixture():
    splitter = RecursiveSplitter(parent_max_chars=600, child_max_chars=120)
    result = splitter.chunk(FIXTURE)
    _assert_invariants(FIXTURE, result)
    assert len(result.parents) > 1
    for parent in result.parents:
        assert len(parent.text) <= 600
        for child in parent.children:
            assert len(child.text) <= 120


def test_empty_and_whitespace_text_has_no_parents():
    splitter = RecursiveSplitter()
    assert splitter.chunk("").parents == []
    assert splitter.chunk("  \n\n \t ").parents == []
    assert splitter.split_sentences("") == []
    assert splitter.split_sentences(" \n ") == []


def test_short_paragraphs_under_limit_stay_one_child():
    text = "First short paragraph.\n\nSecond short paragraph."
    result = RecursiveSplitter().chunk(text)
    assert len(result.parents) == 1
    assert _child_texts(result) == [text]


def test_blank_line_split_only_when_pieces_do_not_merge():
    first = "a" * 30
    second = "b" * 30
    text = f"{first}\n\n{second}"
    result = RecursiveSplitter(child_max_chars=40).chunk(text)
    _assert_invariants(text, result)
    assert _child_texts(result) == [first, second]


def test_oversize_paragraph_splits_at_sentences_not_mid_sentence():
    sentences = [f"Sentence number {i} says something plainly about topic {i}." for i in range(8)]
    text = " ".join(sentences)
    result = RecursiveSplitter(child_max_chars=120).chunk(text)
    _assert_invariants(text, result)
    children = _child_texts(result)
    assert len(children) > 1
    for child in children:
        assert child.endswith(".")
        assert child.startswith("Sentence number")
        assert len(child) <= 120


def test_oversize_run_without_punctuation_splits_at_words():
    words = " ".join(f"word{i}" for i in range(80))
    result = RecursiveSplitter(child_max_chars=60).chunk(words)
    _assert_invariants(words, result)
    for child in result.parents[0].children:
        assert child.char_start == 0 or words[child.char_start - 1] == " "
        assert child.char_end == len(words) or words[child.char_end] == " "
        assert len(child.text) <= 60


def test_long_word_run_is_hard_cut():
    text = "x" * 250
    result = RecursiveSplitter(parent_max_chars=100, child_max_chars=40).chunk(text)
    _assert_invariants(text, result)
    assert all(len(p.text) <= 100 for p in result.parents)
    assert all(len(c.text) <= 40 for p in result.parents for c in p.children)
    assert "".join(c.text for p in result.parents for c in p.children) == text


def test_entity_split_is_vetoed_and_counted_with_real_spacy():
    text = "Reporters at The New York Times wrote about it."
    splitter = RecursiveSplitter(child_max_chars=30)
    result = splitter.chunk(text)
    _assert_invariants(text, result)

    entity_start = text.index("The New York Times")
    entity_end = entity_start + len("The New York Times")
    for child in result.parents[0].children:
        assert not entity_start < child.char_start < entity_end
        assert not entity_start < child.char_end < entity_end
    assert result.stats.entity_vetoes >= 1

    unguarded = RecursiveSplitter(child_max_chars=30, use_entity_guard=False).chunk(text)
    assert any(entity_start < c.char_end < entity_end for c in unguarded.parents[0].children), (
        "without the guard the whitespace level cuts inside the entity"
    )
    assert unguarded.stats.entity_vetoes == 0


class _FakeSpan:
    def __init__(self, start_char: int, end_char: int = 0) -> None:
        self.start_char = start_char
        self.end_char = end_char


class _FakeNlp:
    """Stands in for spaCy: reports fixed entity names and a single sentence."""

    def __init__(self, entity_names: list[str]) -> None:
        self._names = entity_names

    def __call__(self, text: str) -> SimpleNamespace:
        ents = []
        for name in self._names:
            idx = text.find(name)
            if idx >= 0:
                ents.append(_FakeSpan(idx, idx + len(name)))
        return SimpleNamespace(ents=ents, sents=[_FakeSpan(0)])


def test_entity_longer_than_limit_still_splits():
    entity = "Organisation Alpha Beta Gamma Delta Epsilon Zeta"
    text = f"Visit {entity} today."
    splitter = RecursiveSplitter(child_max_chars=20, nlp=_FakeNlp([entity]))
    result = splitter.chunk(text)
    _assert_invariants(text, result)

    entity_start = text.index(entity)
    entity_end = entity_start + len(entity)
    assert any(entity_start < c.char_end < entity_end for c in result.parents[0].children), (
        "an entity that alone exceeds the limit may be split"
    )
    assert result.stats.entity_vetoes == 0
    assert all(len(c.text) <= 20 for c in result.parents[0].children)


def test_split_sentences_uses_punctuation_and_blank_lines():
    text = "First sentence here. Second one.\n\nThird."
    spans = RecursiveSplitter().split_sentences(text)
    assert [text[s:e] for s, e in spans] == ["First sentence here.", "Second one.", "Third."]


def test_params_round_trip_through_make_strategy() -> None:
    """chunk_runs.params must rebuild an identical strategy (``r`` re-run)."""
    from notebooklm._preprocessing.chunking import make_strategy

    original = RecursiveSplitter(parent_max_chars=900, child_max_chars=300)
    rebuilt = make_strategy("recursive", **original.params)
    assert rebuilt.params == original.params
