"""Unit tests for ``run_full_assessment``'s contextual-embedding wiring.

Covers only the new behavior: the notebook's own summary (fetched via
``resolve_notebook_context``) is used as the chunk-embedding context prefix by
default, an explicit ``context_override`` bypasses that fetch, and ``""``
disables the prefix. The rest of ``run_full_assessment`` (transcription,
preprocessing) is stubbed out — it is unchanged by this feature.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import notebooklm._app.assessment as assessment_module
from notebooklm._app.assessment import run_full_assessment


def _make_client() -> MagicMock:
    client = MagicMock()
    client.artifacts.download_audio = AsyncMock(return_value=None)
    return client


@pytest.fixture(autouse=True)
def _stub_pipeline_and_transcription():
    fake_chunk = SimpleNamespace(text="A chunk.", topic_id=0, entities=[])
    with (
        patch.object(assessment_module, "get_artifact", new=AsyncMock(return_value=None)),
        patch.object(
            assessment_module, "get_artifact_prompt", new=AsyncMock(return_value="Be accurate")
        ),
        patch.object(
            assessment_module.TranscriptionService,
            "transcribe_audio",
            return_value={"text": "transcript text", "provider": "deepgram"},
        ),
        patch.object(assessment_module.PreprocessingPipeline, "process", return_value=[fake_chunk]),
        patch.object(
            assessment_module.IngestionService, "ingest_chunks", new=AsyncMock(return_value=1)
        ) as mock_ingest_chunks,
        patch.object(assessment_module, "setup_dspy_router", return_value=(MagicMock(), MagicMock())),
    ):
        yield mock_ingest_chunks


@pytest.mark.asyncio
async def test_run_full_assessment_defaults_to_notebook_summary_context(
    _stub_pipeline_and_transcription,
):
    client = _make_client()
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with patch.object(
        assessment_module,
        "resolve_notebook_context",
        new=AsyncMock(return_value="Notebook summary text."),
    ) as mock_resolve:
        await run_full_assessment(client, session, "nb-1", "art-1")

    mock_resolve.assert_awaited_once_with(client, "nb-1")
    _stub_pipeline_and_transcription.assert_awaited_once()
    assert _stub_pipeline_and_transcription.call_args.kwargs["context"] == "Notebook summary text."


@pytest.mark.asyncio
async def test_run_full_assessment_context_override_skips_auto_fetch(
    _stub_pipeline_and_transcription,
):
    client = _make_client()
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with patch.object(
        assessment_module, "resolve_notebook_context", new=AsyncMock()
    ) as mock_resolve:
        await run_full_assessment(
            client, session, "nb-1", "art-1", context_override="Custom context."
        )

    mock_resolve.assert_not_called()
    assert _stub_pipeline_and_transcription.call_args.kwargs["context"] == "Custom context."


@pytest.mark.asyncio
async def test_run_full_assessment_empty_override_disables_context(
    _stub_pipeline_and_transcription,
):
    client = _make_client()
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    session.execute.return_value = mock_result

    with patch.object(
        assessment_module, "resolve_notebook_context", new=AsyncMock()
    ) as mock_resolve:
        await run_full_assessment(client, session, "nb-1", "art-1", context_override="")

    mock_resolve.assert_not_called()
    assert _stub_pipeline_and_transcription.call_args.kwargs["context"] == ""
