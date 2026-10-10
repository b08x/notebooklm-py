import sys
from unittest.mock import patch

from notebooklm._preprocessing.annotators import (
    BERTopicAnnotator,
    DoclingPIIFilter,
    SpacyAnnotator,
    _redact_spans,
)


def test_spacy_annotator():
    # If spacy is not installed, it falls back to empty lists.
    annotator = SpacyAnnotator()
    res = annotator.annotate("Apple is a company.")
    assert "pos" in res
    assert "lemmas" in res
    assert "entities" in res


def test_spacy_annotator_defaults_to_en_core_web_md():
    annotator = SpacyAnnotator()
    assert annotator.model == "en_core_web_md"


def test_bertopic_annotator():
    annotator = BERTopicAnnotator()
    # Force the fallback: bertopic "not installed" (a None module entry makes
    # ``from bertopic import BERTopic`` raise ImportError).
    with patch.dict(sys.modules, {"bertopic": None}):
        res = annotator.annotate(["doc1", "doc2"])
    assert res == [-1, -1]


def test_docling_pii_filter():
    filter = DoclingPIIFilter()
    res = filter.filter("This is a PII text.")
    assert res == "This is a [REDACTED] text."


def test_redact_spans_only_touches_the_tagged_span():
    # Regression test: a naive `text.replace(entity_text, "[REDACTED]")` would
    # nuke every occurrence of "l" in the whole string, not just the one
    # character actually tagged as an entity — this is exactly what produced
    # "absolutely" -> "abso[REDACTED]ute[REDACTED]y" in a real transcript.
    text = "i mean it is absolutely obvious today, and it is really really large."
    l_index = text.index("l")  # first "l", inside "absolutely"

    result = _redact_spans(text, [(l_index, l_index + 1)])

    assert result.count("[REDACTED]") == 1
    assert "really" in result  # unrelated occurrences of "l" untouched
    assert "large" in result


def test_redact_spans_merges_overlapping_spans():
    text = "abcdef"
    result = _redact_spans(text, [(1, 3), (2, 5)])
    assert result == "a[REDACTED]f"


def test_redact_spans_empty_list_returns_text_unchanged():
    assert _redact_spans("unchanged", []) == "unchanged"
