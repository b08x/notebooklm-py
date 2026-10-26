import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

import notebooklm.auth as auth_module
from notebooklm._app import assessment as assessment_module
from notebooklm._app.assessment import AssessmentChunk, AssessmentResult
from notebooklm.cli import helpers as helpers_module
from notebooklm.notebooklm_cli import cli
from notebooklm.types import Artifact, Notebook

from .conftest import create_mock_client, inject_client


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_auth():
    with (
        patch.object(helpers_module, "load_auth_from_storage") as mock_storage,
        patch.object(
            auth_module, "fetch_tokens_with_domains", new_callable=AsyncMock
        ) as mock_fetch,
    ):
        mock_storage.return_value = {
            "SID": "test",
            "HSID": "test",
            "SSID": "test",
            "APISID": "test",
            "SAPISID": "test",
        }
        mock_fetch.return_value = ("csrf", "session")
        yield


def test_artifact_export_ass_success(runner, mock_auth, tmp_path):
    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(
        return_value=[Notebook(id="nb_123", title="Test Notebook")]
    )
    mock_client.artifacts.list_audio = AsyncMock(
        return_value=[
            Artifact(id="art_audio_1", title="Deep Dive Audio", _artifact_type=1, status=3)
        ]
    )

    fake_chunk = AssessmentChunk(
        text="The climate models were confirmed in 2024.",
        clause_external_id="chunk-1:0",
        fact_check_passed=True,
        fact_check_citations="Confirmed by NOAA records.",
        speaker="Speaker 1",
    )
    fake_result = AssessmentResult(
        system_instructions="Check accuracy",
        audio_metadata=json.dumps({"provider": "cached"}),
        transcript="The climate models were confirmed in 2024.",
        chunks=[fake_chunk],
        sfl_metrics={"total_clauses": 1},
    )

    out_file = str(tmp_path / "custom_assessment.ass")

    with patch.object(
        assessment_module, "run_full_assessment", new_callable=AsyncMock
    ) as mock_assess:
        mock_assess.return_value = fake_result
        res = runner.invoke(
            cli,
            ["artifact", "export-ass", "-n", "nb_123", "-o", out_file],
            obj=inject_client(mock_client),
        )

    assert res.exit_code == 0
    assert "Exported audio assessment to ASS format:" in res.output
    assert out_file in res.output

    with open(out_file, encoding="utf-8") as f:
        content = f.read()

    assert "[Script Info]" in content
    assert "The climate models were confirmed in 2024." in content
    assert "FACT-CHECK: VERIFIED" in content


def test_artifact_export_ass_json(runner, mock_auth, tmp_path):
    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(
        return_value=[Notebook(id="nb_123", title="Test Notebook")]
    )
    mock_client.artifacts.list = AsyncMock(
        return_value=[Artifact(id="art_audio_2", title="Audio Debate", _artifact_type=1, status=3)]
    )

    fake_chunk = AssessmentChunk(
        text="Sample claim.",
        clause_external_id="chunk-2:0",
        fact_check_passed=False,
        fact_check_citations="Contradiction.",
    )
    fake_result = AssessmentResult(
        system_instructions="",
        audio_metadata="{}",
        transcript="Sample claim.",
        chunks=[fake_chunk],
    )

    out_file = str(tmp_path / "json_export.ass")

    with patch.object(
        assessment_module, "run_full_assessment", new_callable=AsyncMock
    ) as mock_assess:
        mock_assess.return_value = fake_result
        res = runner.invoke(
            cli,
            ["artifact", "export-ass", "art_audio_2", "-n", "nb_123", "-o", out_file, "--json"],
            obj=inject_client(mock_client),
        )

    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["status"] == "ok"
    assert data["artifact_id"] == "art_audio_2"
    assert data["total_chunks"] == 1
    assert data["passed_chunks"] == 0
    assert data["failed_chunks"] == 1


def test_artifact_export_assessment_alias(runner, mock_auth, tmp_path):
    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(
        return_value=[Notebook(id="nb_123", title="Test Notebook")]
    )
    mock_client.artifacts.list_audio = AsyncMock(
        return_value=[Artifact(id="art_audio_1", title="Audio", _artifact_type=1, status=3)]
    )

    fake_result = AssessmentResult(
        system_instructions="",
        audio_metadata="{}",
        transcript="Alias test.",
        chunks=[AssessmentChunk(text="Alias test.", clause_external_id="c1")],
    )

    out_file = str(tmp_path / "alias_out.ass")

    with patch.object(
        assessment_module, "run_full_assessment", new_callable=AsyncMock
    ) as mock_assess:
        mock_assess.return_value = fake_result
        res = runner.invoke(
            cli,
            ["artifact", "export-assessment", "-n", "nb_123", "-o", out_file],
            obj=inject_client(mock_client),
        )

    assert res.exit_code == 0
    assert "Exported audio assessment to ASS format:" in res.output


def test_artifact_export_ass_no_audio(runner, mock_auth):
    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(
        return_value=[Notebook(id="nb_123", title="Test Notebook")]
    )
    mock_client.artifacts.list_audio = AsyncMock(return_value=[])

    res = runner.invoke(
        cli,
        ["artifact", "export-ass", "-n", "nb_123"],
        obj=inject_client(mock_client),
    )

    assert res.exit_code == 1
    assert "No audio overview artifact found" in res.output
