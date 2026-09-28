from types import SimpleNamespace

from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import TUIState, View


def test_sort_cycling_with_s_key():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    assert state.sort_key == "name"

    # Cycle 1: name -> modified (Recent Activity)
    assert handle_key("s", state) is True
    assert state.sort_key == "modified"

    # Cycle 2: modified -> recent-artifacts
    assert handle_key("s", state) is True
    assert state.sort_key == "recent-artifacts"

    # Cycle 3: recent-artifacts -> name
    assert handle_key("s", state) is True
    assert state.sort_key == "name"


def test_search_mode_toggle_and_character_entry():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    assert state.searching is False
    assert state.search_query == ""

    # Enter search mode with '/'
    assert handle_key("/", state) is True
    assert state.searching is True

    # Type characters
    for char in "gemini":
        handle_key(char, state)
    assert state.search_query == "gemini"

    # Backspace
    handle_key("\x7f", state)
    assert state.search_query == "gemin"

    # Enter exits search mode but keeps query
    handle_key("\r", state)
    assert state.searching is False
    assert state.search_query == "gemin"


def test_search_escape_behavior():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    state.searching = True
    state.search_query = "claude"

    # Escape clears query and exits searching
    handle_key("\x1b", state)
    assert state.searching is False
    assert state.search_query == ""

    # Next escape operates as normal previous_view navigation
    state.previous_view = View.CHAT
    handle_key("\x1b", state)
    assert state.current_view == View.CHAT


def test_filter_toggles_audio_and_min_sources():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST

    assert state.filter_has_audio is False
    handle_key("o", state)
    assert state.filter_has_audio is True
    handle_key("o", state)
    assert state.filter_has_audio is False

    assert state.filter_min_sources is False
    handle_key("z", state)
    assert state.filter_min_sources is True
    handle_key("z", state)
    assert state.filter_min_sources is False


def test_filtered_and_sorted_notebooks_navigation():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    state.notebooks = [
        SimpleNamespace(
            id="nb-1", title="[GEMINI] Docs", sources_count=3, created_at=None, modified_at=None
        ),
        SimpleNamespace(
            id="nb-2", title="[CLAUDE] Prompts", sources_count=0, created_at=None, modified_at=None
        ),
        SimpleNamespace(
            id="nb-3", title="General Notes", sources_count=5, created_at=None, modified_at=None
        ),
    ]
    state.selected_notebook = "nb-1"

    # Search filter
    state.search_query = "claude"
    filtered = state.get_filtered_and_sorted_notebooks()
    assert len(filtered) == 1
    assert filtered[0].id == "nb-2"

    # Source filter
    state.search_query = ""
    state.filter_min_sources = True
    filtered = state.get_filtered_and_sorted_notebooks()
    assert len(filtered) == 2
    assert {nb.id for nb in filtered} == {"nb-1", "nb-3"}


def test_scrolling_does_not_trigger_background_tasks():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    state.notebooks = [
        SimpleNamespace(id="nb-1", title="A", sources_count=0),
        SimpleNamespace(id="nb-2", title="B", sources_count=0),
        SimpleNamespace(id="nb-3", title="C", sources_count=0),
    ]
    state.selected_notebook = "nb-1"

    # Scrolling j and k should ONLY update selection without launching background tasks
    handle_key("j", state)
    assert state.selected_notebook == "nb-2"
    assert state.background_task is None
    assert state.stats_task is None
    assert state.summary_task is None

    handle_key("j", state)
    assert state.selected_notebook == "nb-3"
    assert state.background_task is None
    assert state.stats_task is None
    assert state.summary_task is None

    handle_key("k", state)
    assert state.selected_notebook == "nb-2"
    assert state.background_task is None
    assert state.stats_task is None
    assert state.summary_task is None
