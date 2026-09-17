from unittest.mock import patch

from notebooklm._preprocessing.annotators import BERTopicAnnotator, DoclingPIIFilter, SpacyAnnotator


def test_spacy_annotator():
    # If spacy is not installed, it falls back to empty lists.
    annotator = SpacyAnnotator()
    res = annotator.annotate("Apple is a company.")
    assert "pos" in res
    assert "lemmas" in res
    assert "entities" in res

@patch("notebooklm._preprocessing.annotators.BERTopicAnnotator._load_model")
def test_bertopic_annotator(mock_load):
    annotator = BERTopicAnnotator()
    # Force it to use the fallback logic by pretending the model didn't load
    annotator.topic_model = None
    res = annotator.annotate(["doc1", "doc2"])
    assert len(res) == 2

def test_docling_pii_filter():
    filter = DoclingPIIFilter()
    res = filter.filter("This is a PII text.")
    assert res == "This is a [REDACTED] text."
