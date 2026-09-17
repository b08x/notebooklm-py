from unittest.mock import patch

from notebooklm._preprocessing.pipeline import Chunk, PreprocessingPipeline


def test_process_returns_structured_chunks_without_fact_check_field():
    pipeline = PreprocessingPipeline()

    with (
        patch.object(pipeline.spacy_ann, "annotate", return_value={"entities": [("Acme", "ORG")]}),
        patch.object(pipeline.topic_ann, "annotate", return_value=[0]),
    ):
        chunks = pipeline.process("Acme announced a new product today.")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, Chunk)
    assert chunk.entities == [("Acme", "ORG")]
    assert chunk.topic_id == 0
    assert not hasattr(chunk, "fact_check_passed")


def test_process_empty_text_returns_no_chunks():
    pipeline = PreprocessingPipeline()
    assert pipeline.process("") == []


def test_process_falls_back_when_spacy_and_bertopic_unavailable():
    pipeline = PreprocessingPipeline()

    with (
        patch.object(pipeline.spacy_ann, "annotate", side_effect=Exception("no spacy")),
        patch.object(pipeline.topic_ann, "annotate", side_effect=Exception("no bertopic")),
    ):
        chunks = pipeline.process("Some plain text without any model available.")

    assert len(chunks) == 1
    assert chunks[0].entities == []
    assert chunks[0].topic_id == -1


def test_chunk_formatted_property_flattens_to_string():
    chunk = Chunk(text="Hello world", topic_id=2, entities=[("world", "GPE")])
    formatted = chunk.formatted
    assert "Hello world" in formatted
    assert "Topic ID: 2" in formatted
    assert "world (GPE)" in formatted


def test_pipeline_has_no_fact_checker():
    """Fact-checking moved to an opt-in, persisted TUI action (see _app.assessment)."""
    pipeline = PreprocessingPipeline()
    assert not hasattr(pipeline, "fact_checker")
