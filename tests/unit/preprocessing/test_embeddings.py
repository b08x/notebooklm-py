from unittest.mock import MagicMock, patch

import httpx
import pytest

from notebooklm._preprocessing.embeddings import OllamaEmbeddingAdapter


def test_embed_empty_list_skips_request():
    adapter = OllamaEmbeddingAdapter()
    assert adapter.embed([]) == []


@patch("notebooklm._preprocessing.embeddings.httpx.post")
def test_embed_returns_vectors_in_order(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"embeddings": [[0.1, 0.1], [0.2, 0.2]]},
        raise_for_status=lambda: None,
    )

    adapter = OllamaEmbeddingAdapter()
    vectors = adapter.embed(["first", "second"])

    assert vectors == [[0.1, 0.1], [0.2, 0.2]]
    mock_post.assert_called_once()
    _, kwargs = mock_post.call_args
    assert kwargs["json"] == {"model": adapter.model, "input": ["first", "second"]}


@patch("notebooklm._preprocessing.embeddings.httpx.post", side_effect=httpx.ConnectError("down"))
def test_embed_wraps_connection_errors(mock_post):
    adapter = OllamaEmbeddingAdapter()
    with pytest.raises(RuntimeError, match="Ollama embedding request failed"):
        adapter.embed(["hello"])


@patch("notebooklm._preprocessing.embeddings.httpx.post")
def test_embed_mismatched_count_raises(mock_post):
    mock_post.return_value = MagicMock(
        status_code=200,
        json=lambda: {"embeddings": [[0.1, 0.1]]},
        raise_for_status=lambda: None,
    )

    adapter = OllamaEmbeddingAdapter()
    with pytest.raises(RuntimeError, match="embeddings"):
        adapter.embed(["first", "second"])


def test_defaults_from_environment(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "custom-model")
    monkeypatch.setenv("OLLAMA_URL", "http://example.internal:1234")

    adapter = OllamaEmbeddingAdapter()

    assert adapter.model == "custom-model"
    assert adapter.base_url == "http://example.internal:1234"
