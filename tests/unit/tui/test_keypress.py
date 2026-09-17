from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import TUIState, View


def test_handle_key_quit():
    state = TUIState()
    assert handle_key("q", state) is False


def test_handle_key_chat_toggle():
    state = TUIState()
    assert state.current_view == View.NOTEBOOK_LIST

    assert handle_key("c", state) is True
    assert state.current_view == View.CHAT
    assert state.previous_view == View.NOTEBOOK_LIST

    assert handle_key("\x1b", state) is True  # Escape
    assert state.current_view == View.NOTEBOOK_LIST
    assert state.previous_view is None


def test_handle_key_compiler_toggle():
    state = TUIState()
    assert handle_key("p", state) is True
    assert state.current_view == View.COMPILER


def test_handle_key_sort_toggle():
    state = TUIState()
    assert state.sort_key == "name"
    assert handle_key("s", state) is True
    assert state.sort_key == "modified"
    assert handle_key("s", state) is True
    assert state.sort_key == "name"


def test_handle_key_chat_input():
    state = TUIState()
    state.current_view = View.CHAT

    handle_key("h", state)
    handle_key("i", state)
    assert state.chat_input == "hi"

    handle_key("\x7f", state)  # backspace
    assert state.chat_input == "h"


def test_handle_key_assessment_toggle():
    state = TUIState()
    assert handle_key("A", state) is True
    assert state.current_view == View.ASSESSMENT

    assert handle_key("\x1b", state) is True  # Escape
    assert state.current_view == View.NOTEBOOK_LIST


def test_handle_key_notebook_detail_ingest_menu_starts_source_selection(monkeypatch):
    from unittest.mock import MagicMock

    from notebooklm.tui.views import notebook_detail

    mock_start_selection = MagicMock()
    monkeypatch.setattr(notebook_detail, "start_source_selection", mock_start_selection)

    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    state.detail_menu_index = 2

    assert handle_key("\r", state) is True

    mock_start_selection.assert_called_once_with(state)
    # Source selection stays on Notebook Detail until sources load; it does
    # not jump straight to Notebook List the way the other menu actions do.
    assert state.current_view == View.NOTEBOOK_DETAIL


def test_handle_key_notebook_detail_assess_menu_starts_assessment(monkeypatch):
    from unittest.mock import MagicMock

    from notebooklm.tui.views import notebook_detail

    mock_start_assess = MagicMock()
    monkeypatch.setattr(notebook_detail, "start_assess_audio_overview", mock_start_assess)

    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    state.detail_menu_index = 3

    assert handle_key("\r", state) is True

    mock_start_assess.assert_called_once_with(state)
    assert state.current_view == View.NOTEBOOK_LIST


def test_handle_key_notebook_detail_menu_clamps_to_three():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.detail_menu_index = 3

    handle_key("j", state)

    assert state.detail_menu_index == 3


def test_handle_key_e_enters_context_edit_mode_seeded_from_summary():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    state.notebook_summaries["nb-1"] = "Auto-fetched notebook summary."

    assert handle_key("e", state) is True

    assert state.editing_context is True
    assert state.context_edit_buffer == "Auto-fetched notebook summary."


def test_handle_key_e_seeds_from_existing_override_over_summary():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    state.notebook_summaries["nb-1"] = "Auto-fetched notebook summary."
    state.context_overrides["nb-1"] = "Previously customized context."

    handle_key("e", state)

    assert state.context_edit_buffer == "Previously customized context."


def test_handle_key_e_ignored_without_selected_notebook():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL

    handle_key("e", state)

    assert state.editing_context is False


def test_context_edit_typing_and_save():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"

    handle_key("e", state)
    handle_key("h", state)
    handle_key("i", state)
    assert state.context_edit_buffer == "hi"

    handle_key("\x7f", state)  # backspace
    assert state.context_edit_buffer == "h"

    assert handle_key("\r", state) is True
    assert state.editing_context is False
    assert state.context_overrides["nb-1"] == "h"


def test_context_edit_escape_cancels_without_saving():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"

    handle_key("e", state)
    handle_key("x", state)
    handle_key("\x1b", state)  # escape

    assert state.editing_context is False
    assert state.context_edit_buffer == ""
    assert "nb-1" not in state.context_overrides


def test_handle_key_n_jumps_to_notebook_detail_when_notebook_selected():
    state = TUIState()
    state.selected_notebook = "nb-1"
    state.current_view = View.COMPILER

    assert handle_key("n", state) is True

    assert state.current_view == View.NOTEBOOK_DETAIL
    assert state.previous_view == View.COMPILER


def test_handle_key_n_jumps_to_notebook_list_when_none_selected():
    state = TUIState()
    state.selected_notebook = None
    state.current_view = View.COMPILER

    assert handle_key("n", state) is True

    assert state.current_view == View.NOTEBOOK_LIST


def test_handle_key_n_survives_multiple_view_hops():
    # Reproduces the reported gap: previous_view is a single slot that gets
    # overwritten by each p/A/L jump, so after more than one hop Esc alone can
    # no longer find its way back — n must work regardless of how many views
    # were visited in between. (Chat is skipped here since once inside it,
    # single-letter keys are captured as chat input, not navigation — a
    # separate, correct behavior, not part of what's being exercised here.)
    state = TUIState()
    state.selected_notebook = "nb-1"
    state.current_view = View.NOTEBOOK_DETAIL

    handle_key("p", state)  # -> Compiler (previous_view now Notebook Detail)
    handle_key("A", state)  # -> Assessment (previous_view now Compiler)
    handle_key("L", state)  # -> Logs (previous_view now Assessment)

    assert handle_key("n", state) is True
    assert state.current_view == View.NOTEBOOK_DETAIL


def test_handle_key_n_noop_when_already_on_target_view():
    state = TUIState()
    state.selected_notebook = "nb-1"
    state.current_view = View.NOTEBOOK_DETAIL
    state.previous_view = View.CHAT

    handle_key("n", state)

    # previous_view is untouched, not clobbered by a no-op jump
    assert state.previous_view == View.CHAT


def test_handle_key_logs_toggle():
    state = TUIState()
    assert handle_key("L", state) is True
    assert state.current_view == View.LOGS

    assert handle_key("\x1b", state) is True  # Escape
    assert state.current_view == View.NOTEBOOK_LIST


def _make_source(source_id: str):
    from types import SimpleNamespace

    return SimpleNamespace(id=source_id, title=f"Source {source_id}")


def test_source_selection_navigation_and_toggle():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selecting_sources = True
    state.ingest_sources = [_make_source("a"), _make_source("b"), _make_source("c")]
    state.ingest_selected = {"a", "b", "c"}

    handle_key("j", state)
    assert state.ingest_cursor == 1

    handle_key(" ", state)  # deselect source "b"
    assert state.ingest_selected == {"a", "c"}

    handle_key(" ", state)  # re-select
    assert state.ingest_selected == {"a", "b", "c"}


def test_source_selection_select_none_and_all():
    state = TUIState()
    state.selecting_sources = True
    state.ingest_sources = [_make_source("a"), _make_source("b")]
    state.ingest_selected = {"a", "b"}

    handle_key("n", state)
    assert state.ingest_selected == set()

    handle_key("a", state)
    assert state.ingest_selected == {"a", "b"}


def test_source_selection_escape_cancels_without_starting_ingestion(monkeypatch):
    from unittest.mock import MagicMock

    from notebooklm.tui.views import notebook_detail

    mock_start_ingestion = MagicMock()
    monkeypatch.setattr(notebook_detail, "start_ingestion", mock_start_ingestion)

    state = TUIState()
    state.selecting_sources = True
    state.ingest_sources = [_make_source("a")]
    state.ingest_selected = {"a"}

    assert handle_key("\x1b", state) is True

    assert state.selecting_sources is False
    mock_start_ingestion.assert_not_called()


def test_source_selection_enter_starts_ingestion_with_selection(monkeypatch):
    from unittest.mock import MagicMock

    from notebooklm.tui.views import notebook_detail

    mock_start_ingestion = MagicMock()
    monkeypatch.setattr(notebook_detail, "start_ingestion", mock_start_ingestion)

    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selecting_sources = True
    state.ingest_sources = [_make_source("a"), _make_source("b")]
    state.ingest_selected = {"a"}

    assert handle_key("\r", state) is True

    assert state.selecting_sources is False
    assert state.current_view == View.NOTEBOOK_LIST
    mock_start_ingestion.assert_called_once_with(state, selected_source_ids={"a"})


def test_handle_key_assessment_fact_check_dispatches(monkeypatch):
    from unittest.mock import MagicMock

    from notebooklm.tui.views import assessment_view

    mock_trigger = MagicMock()
    monkeypatch.setattr(assessment_view, "trigger_fact_check", mock_trigger)

    state = TUIState()
    state.current_view = View.ASSESSMENT

    assert handle_key("f", state) is True
    mock_trigger.assert_called_once_with(state)
