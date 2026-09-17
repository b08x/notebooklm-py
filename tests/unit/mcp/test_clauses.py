"""Unit tests for the ``search_clauses`` MCP tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Skip cleanly when the `mcp` extra (fastmcp) is absent; see conftest.py.
pytest.importorskip("fastmcp")

import notebooklm.db.session as db_session_module  # noqa: E402
import notebooklm.mcp.tools.clauses as clauses_tool_module  # noqa: E402
from notebooklm._app.clause_search import ClauseSearchResult, MatchedClause  # noqa: E402

NB_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_search_clauses_returns_answer_and_matches(mcp_call, mock_client):
    fake_result = ClauseSearchResult(
        answer="It happened in March.",
        matched_clauses=[
            MatchedClause(
                clause_id="src-1:0", document_id="src-1", text="March launch.", distance=0.1
            )
        ],
    )

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(
            clauses_tool_module.core, "search_clauses", new=AsyncMock(return_value=fake_result)
        ) as mock_search,
        patch.object(db_session_module, "async_session_maker", return_value=mock_session),
    ):
        result = await mcp_call(
            "search_clauses", {"notebook": NB_ID, "query": "when was the launch?", "top_k": 3}
        )

    assert result.structured_content["answer"] == "It happened in March."
    assert result.structured_content["matched_clauses"] == [
        {"clause_id": "src-1:0", "document_id": "src-1", "text": "March launch.", "distance": 0.1}
    ]
    mock_search.assert_awaited_once()
    call_kwargs = mock_search.call_args
    assert call_kwargs.args[2] == NB_ID
    assert call_kwargs.args[3] == "when was the launch?"
    assert call_kwargs.kwargs["top_k"] == 3


@pytest.mark.asyncio
async def test_search_clauses_empty_result(mcp_call, mock_client):
    fake_result = ClauseSearchResult(answer="No ingested clauses yet.", matched_clauses=[])

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(
            clauses_tool_module.core, "search_clauses", new=AsyncMock(return_value=fake_result)
        ),
        patch.object(db_session_module, "async_session_maker", return_value=mock_session),
    ):
        result = await mcp_call("search_clauses", {"notebook": NB_ID, "query": "anything"})

    assert result.structured_content["answer"] == "No ingested clauses yet."
    assert result.structured_content["matched_clauses"] == []
