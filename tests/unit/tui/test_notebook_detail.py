from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import notebooklm._app.assessment as assessment_module
import notebooklm._preprocessing.ingestion as ingestion_module
import notebooklm.db.session as db_session_module
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.views import notebook_detail
from notebooklm.tui.views.notebook_detail import (
    _assess_audio_overview_async,
    _ingest_notebook_async,
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


@pytest.mark.asyncio
async def test_ingest_notebook_async_sums_clause_counts():
    client = _make_client(["src-1", "src-2"])

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(
            ingestion_module.IngestionService,
            "ingest_source",
            new=AsyncMock(side_effect=[3, 5]),
        ),
    ):
        _patched_session_maker(mock_maker)

        result = await _ingest_notebook_async("nb-1")

    assert "Ingested 8 clauses from 2 sources." in result


@pytest.mark.asyncio
async def test_ingest_notebook_async_reports_source_failures():
    client = _make_client(["src-1", "src-2"])

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(
            ingestion_module.IngestionService,
            "ingest_source",
            new=AsyncMock(side_effect=[Exception("boom"), 4]),
        ),
    ):
        _patched_session_maker(mock_maker)

        result = await _ingest_notebook_async("nb-1")

    assert "Ingested 4 clauses from 2 sources." in result
    assert "1 source(s) failed" in result


def test_start_ingestion_noop_without_selected_notebook():
    state = TUIState()
    state.selected_notebook = None
    start_ingestion(state)
    assert state.background_task is None


@pytest.mark.asyncio
async def test_ingest_notebook_async_filters_by_selected_source_ids():
    client = _make_client(["src-1", "src-2", "src-3"])

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(
            ingestion_module.IngestionService,
            "ingest_source",
            new=AsyncMock(return_value=2),
        ) as mock_ingest_source,
    ):
        _patched_session_maker(mock_maker)

        result = await _ingest_notebook_async("nb-1", selected_source_ids={"src-1", "src-3"})

    assert "Ingested 4 clauses from 2 sources." in result
    ingested_ids = {call.args[2] for call in mock_ingest_source.call_args_list}
    assert ingested_ids == {"src-1", "src-3"}


@pytest.mark.asyncio
async def test_ingest_notebook_async_updates_progress_dict_live():
    client = _make_client(["src-1", "src-2"])
    progress: dict = {}

    async def fake_ingest_source(self, session, notebook_id, source_id, **kwargs):
        on_progress = kwargs.get("on_progress")
        if on_progress:
            on_progress(1, 2)
            on_progress(2, 2)
        return 2

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
        patch.object(ingestion_module.IngestionService, "ingest_source", new=fake_ingest_source),
    ):
        _patched_session_maker(mock_maker)

        await _ingest_notebook_async("nb-1", progress=progress)

    assert progress["total_sources"] == 2
    assert progress["done_sources"] == 2
    assert progress["current_chunks_done"] == 2
    assert progress["current_chunks_total"] == 2
    assert progress["failures"] == []


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
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch.object(notebook_detail.NotebookLMClient, "from_storage", return_value=client),
        patch.object(db_session_module, "async_session_maker") as mock_maker,
    ):
        _patched_session_maker(mock_maker)

        outcome = await _assess_audio_overview_async("nb-1")

    assert "error" in outcome
    assert "No generated audio overview" in outcome["error"]


def test_start_assess_audio_overview_noop_without_selected_notebook():
    state = TUIState()
    state.selected_notebook = None
    start_assess_audio_overview(state)
    assert state.background_task is None


def test_run_assess_audio_overview_no_artifact_sets_error_not_view_switch():
    client = MagicMock()
    client.artifacts.list_audio = AsyncMock(return_value=[])
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

    assert state.error_message == "No generated audio overview found for nb-1."
    assert state.current_view == View.NOTEBOOK_DETAIL
