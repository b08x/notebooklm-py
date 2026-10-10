from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import notebooklm._app.assessment as assessment_module
import notebooklm.db.session as db_session_module
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.views import assessment_view, notebook_detail
from notebooklm.tui.views.notebook_detail import (
    _assess_audio_overview_async,
    _run_fetch_sources,
    start_assess_audio_overview,
    start_ingestion,
    start_source_selection,
)


def _make_client(source_ids: list[str]) -> MagicMock:
    client = MagicMock()
    client.sources.list = AsyncMock(return_value=[SimpleNamespace(id=sid) for sid in source_ids])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


def _patched_session_maker(mock_maker) -> MagicMock:
    mock_session = MagicMock()
    mock_maker.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_maker.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_session


def test_start_ingestion_noop_without_selected_notebook():
    state = TUIState()
    state.selected_notebook = None
    start_ingestion(state)
    assert state.background_task is None
    assert state.job_store is None


def test_start_source_selection_noop_without_selected_notebook():
    state = TUIState()
    state.selected_notebook = None
    start_source_selection(state)
    assert state.source_fetch_task is None


def test_run_fetch_sources_populates_state_and_opens_picker():
    client = _make_client(["src-1", "src-2"])
    state = TUIState()

    with patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client):
        _run_fetch_sources(state, "nb-1")

    assert [s.id for s in state.ingest_sources] == ["src-1", "src-2"]
    assert state.ingest_selected == {"src-1", "src-2"}  # all pre-selected by default
    assert state.selecting_sources is True
    assert state.ingest_cursor == 0


def test_run_fetch_sources_sets_error_message_on_failure():
    client = MagicMock()
    client.sources.list = AsyncMock(side_effect=Exception("network down"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    state = TUIState()

    with patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client):
        _run_fetch_sources(state, "nb-1")

    assert state.selecting_sources is False
    assert "network down" in state.error_message


def _make_client_with_audio(artifact_id: str = "art-1") -> MagicMock:
    client = MagicMock()
    client.artifacts.list_audio = AsyncMock(
        return_value=[SimpleNamespace(id=artifact_id, created_at=100)]
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.asyncio
async def test_assess_audio_overview_async_populates_assessment_state():
    client = _make_client_with_audio("art-1")
    fake_result = SimpleNamespace(
        system_instructions="Be accurate",
        audio_metadata='{"provider": "deepgram"}',
        chunks=[SimpleNamespace(text="chunk 1")],
        sfl_metrics={"total_clauses": 10},
    )

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(
            assessment_module,
            "run_full_assessment",
            new=AsyncMock(return_value=fake_result),
        ),
    ):
        _patched_session_maker(mock_maker)

        outcome = await _assess_audio_overview_async("nb-1")

    assert "error" not in outcome
    assert outcome["assessment_state"]["system_instructions"] == "Be accurate"
    assert outcome["assessment_state"]["chunks"] == fake_result.chunks


@pytest.mark.asyncio
async def test_assess_audio_overview_async_no_audio_artifact_sets_error():
    client = MagicMock()
    client.artifacts.list_audio = AsyncMock(return_value=[])
    client.sources.list = AsyncMock(return_value=[])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
    ):
        _patched_session_maker(mock_maker)

        outcome = await _assess_audio_overview_async("nb-1")

    assert "error" in outcome
    assert "No assessable content found" in outcome["error"]


@pytest.mark.asyncio
async def test_assess_audio_overview_async_falls_back_to_source_assessment():
    client = MagicMock()
    client.artifacts.list_audio = AsyncMock(return_value=[])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    fake_result = SimpleNamespace(
        system_instructions="Source instructions",
        audio_metadata='{"mode": "sources"}',
        chunks=[SimpleNamespace(text="source chunk 1")],
        sfl_metrics={"total_clauses": 5},
    )

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(
            assessment_module,
            "run_source_assessment",
            new=AsyncMock(return_value=fake_result),
        ),
    ):
        _patched_session_maker(mock_maker)

        outcome = await _assess_audio_overview_async("nb-1")

    assert "error" not in outcome
    assert outcome["assessment_state"]["assessment_mode"] == "sources"
    assert outcome["assessment_state"]["artifact_id"] is None
    assert outcome["assessment_state"]["chunks"] == fake_result.chunks


def test_start_assess_audio_overview_noop_without_selected_notebook():
    state = TUIState()
    state.selected_notebook = None
    start_assess_audio_overview(state)
    assert state.background_task is None


def test_run_assess_audio_overview_no_artifact_sets_error_not_view_switch():
    client = MagicMock()
    client.artifacts.list_audio = AsyncMock(return_value=[])
    client.sources.list = AsyncMock(return_value=[])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
    ):
        _patched_session_maker(mock_maker)

        notebook_detail._run_assess_audio_overview(state, "nb-1")

    assert (
        state.error_message
        == "No assessable content found — generate an audio overview or ingest sources first."
    )
    assert state.current_view == View.NOTEBOOK_DETAIL


def test_run_assess_audio_overview_source_fallback_switches_view():
    client = MagicMock()
    client.artifacts.list_audio = AsyncMock(return_value=[])
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    fake_result = SimpleNamespace(
        system_instructions="Source instructions",
        audio_metadata='{"mode": "sources"}',
        chunks=[SimpleNamespace(text="source chunk 1")],
        sfl_metrics={"total_clauses": 5},
    )

    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(
            assessment_module,
            "run_source_assessment",
            new=AsyncMock(return_value=fake_result),
        ),
        patch.object(assessment_view, "trigger_fact_check"),
    ):
        _patched_session_maker(mock_maker)

        notebook_detail._run_assess_audio_overview(state, "nb-1")

    assert state.error_message is None
    assert state.current_view == View.ASSESSMENT
    assert state.assessment_state["assessment_mode"] == "sources"


# --- notes in the ingestion picker (notebook-curation goal, step 4b) ------------


@pytest.mark.asyncio
async def test_fetch_sources_async_returns_notes_tagged_for_picker():
    from notebooklm.tui.views.notebook_detail import _fetch_sources_async

    client = _make_client(["src-1"])
    client.notes.list = AsyncMock(
        return_value=[SimpleNamespace(id="note-1", title="Meeting note", content="body")]
    )

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
    ):
        mock_session = _patched_session_maker(mock_maker)
        mock_session.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )

        items, ingested = await _fetch_sources_async("nb-1")

    kinds = {item.kind: item.id for item in items}
    assert kinds == {"source": "src-1", "note": "note-1"}
    note_item = next(item for item in items if item.kind == "note")
    assert note_item.title == "Meeting note"
    assert note_item.content == "body"
    assert ingested == set()
