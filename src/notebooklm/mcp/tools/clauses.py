"""Clause-search MCP tools.

Thin adapter over ``_app.clause_search.search_clauses``: semantic search over a
notebook's ingested clauses (regular sources plus any audio-overview
transcript), answered by an LLM. Deliberately separate from ``chat_ask``, which
stays wired to NotebookLM's own chat/citations surface — this tool queries this
project's own local Postgres/pgvector ingestion store instead.

This module imports NO ``click`` / ``rich`` / ``cli``.
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context

from ..._app import clause_search as core
from .._confirm import READ_ONLY
from .._context import get_client
from .._errors import mcp_errors
from .._resolve import resolve_notebook


def register(mcp: Any) -> None:
    """Register the clause-search tool on ``mcp``."""

    @mcp.tool(annotations=READ_ONLY)
    async def search_clauses(
        ctx: Context,
        notebook: str,
        query: str,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Semantically search this project's ingested clauses (separate from ``chat_ask``).

        Returns ``answer`` and ``matched_clauses`` (``clause_id``/``document_id``/
        ``text``/``distance``, lower distance = closer).
        """
        client = get_client(ctx)
        with mcp_errors():
            nb_id = await resolve_notebook(client, notebook)

            from notebooklm.db.session import async_session_maker

            async with async_session_maker() as session:
                result = await core.search_clauses(client, session, nb_id, query, top_k=top_k)

            return {
                "answer": result.answer,
                "matched_clauses": [
                    {
                        "clause_id": m.clause_id,
                        "document_id": m.document_id,
                        "text": m.text,
                        "distance": m.distance,
                    }
                    for m in result.matched_clauses
                ],
            }
