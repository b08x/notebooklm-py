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
