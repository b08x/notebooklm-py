"""Unit tests for ``run_source_assessment`` in ``notebooklm._app.assessment``."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import dspy
import pytest

import notebooklm._app.assessment as assessment_module
import notebooklm._preprocessing.sfl_engine as sfl_engine_module
from notebooklm._app.assessment import AssessmentResult, run_source_assessment


def _make_client(source_ids: list[str]) -> MagicMock:
    client = MagicMock()
    client.sources.list = AsyncMock(return_value=[SimpleNamespace(id=sid) for sid in source_ids])
    return client


def _make_clause(external_id: str, document_id: str, text: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        external_id=external_id,
        document_id=document_id,
        text=text,
        sentence_index=0,
        root_index=0,
        tokens=None,
        groups=None,
        fact_check_passed=None,
    )


@pytest.mark.asyncio
async def test_run_source_assessment_happy_path():
    client = _make_client(["src-1", "src-2"])
    session = AsyncMock()

    clauses = [
        _make_clause("src-1:0", "src-1", "Revenue reached $10M in Q2."),
        _make_clause("src-2:0", "src-2", "Customer retention is 95%."),
    ]
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = clauses
    session.execute.return_value = exec_result

    fake_sfl_res = {"ideational": "finance", "interpersonal": "statement"}
    fake_detector_res = SimpleNamespace(contains_facts=True)
    fake_fc_res = assessment_module.FactCheckResult(
        clause_external_id="src-1:0",
        passed=True,
        framework_available=True,
        citations="Verified via financial report.",
    )

    with (
        patch.object(
            assessment_module, "setup_dspy_router", return_value=(MagicMock(), MagicMock())
        ),
        patch.object(
            assessment_module,
            "resolve_notebook_context",
            new=AsyncMock(return_value="Financial notebook summary."),
        ) as mock_resolve,
        patch.object(
            sfl_engine_module,
            "analyze_transcript",
            return_value={"total_clauses": 2},
        ),
        patch.object(sfl_engine_module, "SFLEngine") as mock_sfl_cls,
        patch.object(dspy, "Predict") as mock_predict_cls,
        patch.object(
            assessment_module,
            "run_fact_check_for_chunk",
            new=AsyncMock(return_value=fake_fc_res),
        ) as mock_fact_check,
    ):
        mock_sfl_cls.return_value.side_effect = lambda utterance: fake_sfl_res
        mock_predict_cls.return_value.side_effect = lambda **kwargs: fake_detector_res

        progress_calls = []
        state_calls = []

        result = await run_source_assessment(
            client,
            session,
            "nb-1",
            progress_callback=lambda msg: progress_calls.append(msg),
            state_callback=lambda k, v: state_calls.append((k, v)),
        )

    assert isinstance(result, AssessmentResult)
    mock_resolve.assert_awaited_once_with(client, "nb-1")
    assert result.system_instructions == "Financial notebook summary."
    assert result.transcript == ""

    metadata = json.loads(result.audio_metadata)
    assert metadata["mode"] == "sources"
    assert metadata["source_ids"] == ["src-1", "src-2"]
    assert metadata["source_count"] == 2

    assert len(result.chunks) == 2
    assert result.chunks[0].text == "Revenue reached $10M in Q2."
    assert result.chunks[0].clause_external_id == "src-1:0"
    assert result.chunks[0].fact_check_passed is True
    assert result.chunks[0].fact_check_citations == "Verified via financial report."

    assert mock_fact_check.await_count == 2
    assert any("Listing notebook sources" in str(c) for c in progress_calls)
    assert any(k == "ticker_stream_append" for k, _ in state_calls)


@pytest.mark.asyncio
async def test_run_source_assessment_no_sources_raises():
    client = _make_client([])
    session = AsyncMock()

    with (
        patch.object(
            assessment_module, "setup_dspy_router", return_value=(MagicMock(), MagicMock())
        ),
        pytest.raises(ValueError, match="No ingested source clauses found for notebook nb-empty"),
    ):
        await run_source_assessment(client, session, "nb-empty")


@pytest.mark.asyncio
async def test_run_source_assessment_no_clauses_raises():
    client = _make_client(["src-1"])
    session = AsyncMock()
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = []
    session.execute.return_value = exec_result

    with (
        patch.object(
            assessment_module, "setup_dspy_router", return_value=(MagicMock(), MagicMock())
        ),
        pytest.raises(ValueError, match="No ingested source clauses found for notebook nb-1"),
    ):
        await run_source_assessment(client, session, "nb-1")


@pytest.mark.asyncio
async def test_run_source_assessment_context_override():
    client = _make_client(["src-1"])
    session = AsyncMock()
    clauses = [_make_clause("src-1:0", "src-1", "Some content.")]
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = clauses
    session.execute.return_value = exec_result

    fake_fc_res = assessment_module.FactCheckResult(
        clause_external_id="src-1:0",
        passed=True,
        framework_available=True,
        citations="Citations",
    )

    with (
        patch.object(
            assessment_module, "setup_dspy_router", return_value=(MagicMock(), MagicMock())
        ),
        patch.object(
            assessment_module, "resolve_notebook_context", new=AsyncMock()
        ) as mock_resolve,
        patch.object(sfl_engine_module, "analyze_transcript", return_value={}),
        patch.object(sfl_engine_module, "SFLEngine"),
        patch.object(
            dspy, "Predict", return_value=lambda **kwargs: SimpleNamespace(contains_facts=True)
        ),
        patch.object(
            assessment_module,
            "run_fact_check_for_chunk",
            new=AsyncMock(return_value=fake_fc_res),
        ) as mock_fc,
    ):
        result = await run_source_assessment(
            client, session, "nb-1", context_override="Custom context override."
        )

    mock_resolve.assert_not_called()
    assert result.system_instructions == "Custom context override."
    assert mock_fc.await_args.args[2] == "Custom context override."


@pytest.mark.asyncio
async def test_run_source_assessment_hitl_skip():
    client = _make_client(["src-1"])
    session = AsyncMock()
    clauses = [_make_clause("src-1:0", "src-1", "Welcome to the notes.")]
    exec_result = MagicMock()
    exec_result.scalars.return_value.all.return_value = clauses
    session.execute.return_value = exec_result

    hitl_called = []

    def mock_hitl(text, sfl):
        hitl_called.append((text, sfl))
        return True  # Skip fact-check

    with (
        patch.object(
            assessment_module, "setup_dspy_router", return_value=(MagicMock(), MagicMock())
        ),
        patch.object(assessment_module, "resolve_notebook_context", new=AsyncMock(return_value="")),
        patch.object(sfl_engine_module, "analyze_transcript", return_value={}),
        patch.object(sfl_engine_module, "SFLEngine"),
        patch.object(
            dspy, "Predict", return_value=lambda **kwargs: SimpleNamespace(contains_facts=False)
        ),
        patch.object(assessment_module, "run_fact_check_for_chunk", new=AsyncMock()) as mock_fc,
    ):
        result = await run_source_assessment(client, session, "nb-1", hitl_callback=mock_hitl)

    assert len(hitl_called) == 1
    mock_fc.assert_not_called()
    assert result.chunks[0].fact_check_passed is True
    assert "Bypassed" in result.chunks[0].fact_check_citations
