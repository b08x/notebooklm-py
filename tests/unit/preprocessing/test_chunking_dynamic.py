import re
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import dspy

from notebooklm._preprocessing.chunking.base import ChunkResult
from notebooklm._preprocessing.chunking.dynamic import DynamicWindowChunker

TEXT = (
    "Alpha starts here. Beta follows it. Gamma adds more. Delta is next. Epsilon ends. Zeta last."
)


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(r"\S[^.!?]*[.!?]", text)]


class FakePredictor:
    def __init__(self, boundaries=None, error=None):
        self.boundaries = boundaries
        self.error = error
        self.calls: list[dict] = []
        self.threads: list[threading.Thread] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        self.threads.append(threading.current_thread())
        if self.error is not None:
            raise self.error
        return SimpleNamespace(boundaries=self.boundaries)


def _chunker(predictor, **kwargs) -> DynamicWindowChunker:
    kwargs.setdefault("min_child_chars", 10)
    kwargs.setdefault("max_child_chars", 1200)
    kwargs.setdefault("parent_max_chars", 4000)
    return DynamicWindowChunker(predictor=predictor, sentence_spans=_sentence_spans, **kwargs)


def _child_texts(result: ChunkResult) -> list[str]:
    return [c.text for p in result.parents for c in p.children]


def _assert_invariants(text: str, result: ChunkResult) -> None:
    prev_end = 0
    for parent in result.parents:
        assert parent.text == text[parent.char_start : parent.char_end]
        assert parent.children
        for child in parent.children:
            assert child.text == text[child.char_start : child.char_end]
            assert child.text.strip()
            assert parent.char_start <= child.char_start < child.char_end <= parent.char_end
            assert child.char_start >= prev_end
            prev_end = child.char_end


def test_identity() -> None:
    chunker = DynamicWindowChunker(predictor=FakePredictor([]), sentence_spans=_sentence_spans)
    assert chunker.name == "dynamic_window"
    assert chunker.version == "1"
    assert chunker.params == {
        "min_child_chars": 200,
        "max_child_chars": 1200,
        "parent_max_chars": 4000,
    }


def test_valid_bounds_are_honoured() -> None:
    predictor = FakePredictor([2, 4])
    result = _chunker(predictor).chunk(TEXT)

    assert _child_texts(result) == [
        "Alpha starts here. Beta follows it.",
        "Gamma adds more. Delta is next.",
        "Epsilon ends. Zeta last.",
    ]
    assert result.stats.extra["fallback"] is False
    assert result.stats.extra["fallback_count"] == 0
    _assert_invariants(TEXT, result)
    call = predictor.calls[0]
    assert len(call["sentences"]) == 6
    assert call["min_chars"] == 10
    assert call["max_chars"] == 1200


def test_unsorted_and_out_of_range_bounds_are_cleaned() -> None:
    # Keeps 4 then 5; drops 0, 2 (not increasing), 9 and -1 (out of range),
    # repeated 4, non-int "x" and bool True.
    predictor = FakePredictor([4, 0, 2, 2, 9, -1, 4, "x", True, 5])
    result = _chunker(predictor).chunk(TEXT)

    assert _child_texts(result) == [
        "Alpha starts here. Beta follows it. Gamma adds more. Delta is next.",
        "Epsilon ends.",
        "Zeta last.",
    ]
    assert result.stats.extra["fallback"] is False
    _assert_invariants(TEXT, result)


def test_raising_predictor_sets_fallback_flag() -> None:
    predictor = FakePredictor(error=RuntimeError("LM down"))
    result = _chunker(predictor, max_child_chars=40).chunk(TEXT)

    assert result.stats.extra["fallback"] is True
    assert result.stats.extra["fallback_count"] == 1
    assert all(len(text) <= 40 for text in _child_texts(result))
    assert len(_child_texts(result)) > 1
    _assert_invariants(TEXT, result)


def test_non_list_output_sets_fallback_flag() -> None:
    result = _chunker(FakePredictor(boundaries=None), max_child_chars=40).chunk(TEXT)

    assert result.stats.extra["fallback"] is True
    _assert_invariants(TEXT, result)


def test_oversize_child_triggers_fallback() -> None:
    # Boundary at 1 leaves a 5-sentence child far above max_child_chars.
    predictor = FakePredictor([1])
    result = _chunker(predictor, max_child_chars=60).chunk(TEXT)

    assert result.stats.extra["fallback"] is True
    assert all(len(text) <= 60 for text in _child_texts(result))
    _assert_invariants(TEXT, result)


def test_empty_bounds_when_split_required_triggers_fallback() -> None:
    result = _chunker(FakePredictor([]), max_child_chars=60).chunk(TEXT)

    assert result.stats.extra["fallback"] is True
    assert all(len(text) <= 60 for text in _child_texts(result))


def test_empty_bounds_when_parent_fits_is_not_a_fallback() -> None:
    result = _chunker(FakePredictor([])).chunk(TEXT)

    assert _child_texts(result) == [TEXT]
    assert result.stats.extra["fallback"] is False


def test_oversize_single_sentence_is_hard_split() -> None:
    text = "word " * 100 + "end."
    result = _chunker(FakePredictor([]), max_child_chars=50).chunk(text)

    assert result.stats.extra["fallback"] is True
    assert all(0 < len(child) <= 50 for child in _child_texts(result))
    _assert_invariants(text, result)


def test_blank_line_blocks_become_parents() -> None:
    text = "Para one. Para one again.\n\nPara two here. Also here."
    result = _chunker(FakePredictor([]), max_child_chars=30, parent_max_chars=30).chunk(text)

    assert [p.text for p in result.parents] == [
        "Para one. Para one again.",
        "Para two here. Also here.",
    ]
    _assert_invariants(text, result)


def test_empty_text_yields_no_parents() -> None:
    result = _chunker(FakePredictor([])).chunk("   \n\n  ")

    assert result.parents == []
    assert result.stats.extra["fallback"] is False


def test_predictor_runs_in_worker_thread_without_dspy_configure(monkeypatch) -> None:
    def _forbidden(*args, **kwargs):
        raise AssertionError("dspy.configure must not run in a worker thread")

    monkeypatch.setattr(dspy, "configure", _forbidden)
    predictor = FakePredictor([3])
    chunker = _chunker(predictor)

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(chunker.chunk, TEXT).result()

    assert predictor.threads and predictor.threads[0] is not threading.main_thread()
    assert len(result.parents[0].children) == 2
    assert result.stats.extra["fallback"] is False
