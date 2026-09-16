from notebooklm.tui.state import TUIState, View


def test_state_initialization():
    state = TUIState()
    assert state.current_view == View.NOTEBOOK_LIST
    assert state.previous_view is None
    assert state.notebooks == []
    assert state.chat_history == []
    assert state.chat_input == ""
    assert state.sort_key == "name"
    assert state.sidebar_focus is True
    assert state.compiler_state == {}
    assert state.selected_notebook is None
