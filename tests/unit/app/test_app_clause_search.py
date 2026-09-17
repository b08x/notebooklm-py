"""Unit tests for the transport-neutral ``notebooklm._app.clause_search`` core."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import dspy
import pytest

import notebooklm._app.clause_search as clause_search_module
from notebooklm._app.clause_search import ClauseSearchResult, search_clauses


def _make_client(source_ids: list[str], audio_artifact_ids: list[str]) -> MagicMock:
    client = MagicMock()
    client.sources.list = AsyncMock(return_value=[SimpleNamespace(id=sid) for sid in source_ids])
    client.artifacts.list_audio = AsyncMock(
        return_value=[SimpleNamespace(id=aid) for aid in audio_artifact_ids]
    )
    return client


def _make_row(clause_id: str, document_id: str, text: str, distance: float):
    clause = SimpleNamespace(external_id=clause_id, document_id=document_id, text=text)
    return (clause, distance)


@pytest.mark.asyncio
async def test_search_clauses_no_ingested_documents_short_circuits():
    client = _make_client([], [])
    session = MagicMock()
    embedder = MagicMock()

    result = await search_clauses(client, session, "nb-1", "what happened?", embedder=embedder)

    assert isinstance(result, ClauseSearchResult)
    assert result.matched_clauses == []
    assert "no ingested clauses" in result.answer.lower()
    embedder.embed.assert_not_called()
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_clauses_embeds_queries_and_synthesizes_answer():
    client = _make_client(["src-1"], ["artifact-1"])
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2, 0.3]]

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.all.return_value = [
        _make_row("src-1:0", "src-1", "The launch happened in March.", 0.05),
        _make_row("artifact-1:2", "artifact-1", "Revenue grew by 12%.", 0.12),
    ]
    session.execute = AsyncMock(return_value=exec_result)

    fake_prediction = SimpleNamespace(answer="The launch was in March; revenue grew 12%.")

    with (
        patch.object(clause_search_module, "setup_dspy_router") as mock_setup,
        patch.object(dspy, "Predict") as mock_predict_cls,
    ):
        mock_predict_cls.return_value = MagicMock(return_value=fake_prediction)

        result = await search_clauses(
            client, session, "nb-1", "when did the launch happen?", top_k=2, embedder=embedder
        )

    mock_setup.assert_called_once()
    embedder.embed.assert_called_once_with(["when did the launch happen?"])
    assert result.answer == "The launch was in March; revenue grew 12%."
    assert len(result.matched_clauses) == 2
    assert result.matched_clauses[0].clause_id == "src-1:0"
    assert result.matched_clauses[0].document_id == "src-1"
    assert result.matched_clauses[0].distance == 0.05


@pytest.mark.asyncio
async def test_search_clauses_no_matches_returns_explanatory_answer():
    client = _make_client(["src-1"], [])
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2, 0.3]]

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.all.return_value = []
    session.execute = AsyncMock(return_value=exec_result)

    result = await search_clauses(client, session, "nb-1", "irrelevant query", embedder=embedder)

    assert result.matched_clauses == []
    assert "no matching clauses" in result.answer.lower()


@pytest.mark.asyncio
async def test_search_clauses_llm_failure_falls_back_gracefully():
    client = _make_client(["src-1"], [])
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2, 0.3]]

    session = MagicMock()
    exec_result = MagicMock()
    exec_result.all.return_value = [_make_row("src-1:0", "src-1", "Some text.", 0.2)]
    session.execute = AsyncMock(return_value=exec_result)

    with (
        patch.object(clause_search_module, "setup_dspy_router"),
        patch.object(dspy, "Predict") as mock_predict_cls,
    ):
        mock_predict_cls.return_value = MagicMock(side_effect=Exception("LLM unreachable"))

        result = await search_clauses(client, session, "nb-1", "a query", embedder=embedder)

    assert len(result.matched_clauses) == 1
    assert "unavailable" in result.answer.lower()
