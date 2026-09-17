import contextlib
import os
import select
import sys
import termios
import tty

from .state import TUIState, View


@contextlib.contextmanager
def raw_terminal():
    if not sys.stdin.isatty():
        yield
        return

    import typing

    fd = typing.cast(int, sys.stdin.fileno())
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def parse_keys(buffer: str) -> list[str]:
    keys = []
    i = 0
    while i < len(buffer):
        if buffer[i] == "\x1b":
            if i + 1 < len(buffer) and buffer[i + 1] in ("[", "O"):
                end = i + 2
                while end < len(buffer) and not buffer[end].isalpha() and buffer[end] != "~":
                    end += 1
                if end < len(buffer):
                    keys.append(buffer[i : end + 1])
                    i = end + 1
                    continue
            keys.append("\x1b")
            i += 1
        else:
            keys.append(buffer[i])
            i += 1
    return keys


def get_keys() -> list[str]:
    """Non-blocking read of all available characters, parsed into distinct keystrokes."""
    if not sys.stdin.isatty():
        return []
    fd = sys.stdin.fileno()
    r, _, _ = select.select([fd], [], [], 0.05)
    if r:
        buffer = os.read(fd, 1024).decode("utf-8")
        return parse_keys(buffer)
    return []


def handle_key(key: str, state: TUIState) -> bool:
    """Returns False to quit, True otherwise."""
    if key == "\x1b[A":
        key = "k"
    elif key == "\x1b[B":
        key = "j"

    if state.editing_context:
        if key == "\x1b":  # Escape cancels without saving
            state.editing_context = False
            state.context_edit_buffer = ""
            return True
        elif key == "\r" or key == "\n":
            if state.selected_notebook:
                state.context_overrides[state.selected_notebook] = state.context_edit_buffer.strip()
            state.editing_context = False
            state.context_edit_buffer = ""
            return True
        elif key == "\x7f":  # Backspace
            state.context_edit_buffer = state.context_edit_buffer[:-1]
            return True
        elif len(key) == 1 and not key.startswith("\x1b"):  # Printable character
            state.context_edit_buffer += key
            return True
        return True

    if state.selecting_sources:
        if key == "\x1b":  # Escape cancels the selection, keeps Notebook Detail up
            state.selecting_sources = False
            return True
        elif key in ("j", "k") and state.ingest_sources:
            if key == "j":
                state.ingest_cursor = min(state.ingest_cursor + 1, len(state.ingest_sources) - 1)
            else:
                state.ingest_cursor = max(state.ingest_cursor - 1, 0)
            return True
        elif key == " " and state.ingest_sources:
            src = state.ingest_sources[state.ingest_cursor]
            if src.id in state.ingest_selected:
                state.ingest_selected.discard(src.id)
            else:
                state.ingest_selected.add(src.id)
            return True
        elif key == "a":
            state.ingest_selected = {s.id for s in state.ingest_sources}
            return True
        elif key == "n":
            state.ingest_selected = set()
            return True
        elif key == "\r" or key == "\n":
            from .views.notebook_detail import start_ingestion

            state.selecting_sources = False
            start_ingestion(state, selected_source_ids=set(state.ingest_selected))
            state.previous_view = state.current_view
            state.current_view = View.NOTEBOOK_LIST
            return True
        return True

    if state.current_view == View.CHAT:
        if key == "\x1b" or key == "\t":  # Escape or Tab
            if state.previous_view:
                state.current_view = state.previous_view
                state.previous_view = None
            return True
        elif key == "\r" or key == "\n":
            if state.chat_input.strip():
                # trigger chat send in background
                from .views.chat_view import submit_chat_message

                submit_chat_message(state)
            return True
        elif key == "\x7f":  # Backspace
            state.chat_input = state.chat_input[:-1]
            return True
        elif len(key) == 1 and not key.startswith("\x1b"):  # Printable character
            state.chat_input += key
            return True

    elif state.current_view == View.COMPILER:
        if key == "\x1b":  # Escape
            if state.previous_view:
                state.current_view = state.previous_view
                state.previous_view = None
            return True
        elif key in ("j", "k"):
            configs = state.compiler_state.get("configs", [])
            selected_idx = state.compiler_state.get("selected_config", 0)
            if configs:
                if key == "j":
                    selected_idx = min(selected_idx + 1, len(configs) - 1)
                else:
                    selected_idx = max(selected_idx - 1, 0)
                state.compiler_state["selected_config"] = selected_idx
            return True
        elif key == "\r" or key == "\n":
            from .views.compiler_view import compile_selected

            compile_selected(state)
            return True

    elif state.current_view == View.ASSESSMENT:
        if key == "\x1b":  # Escape
            if state.previous_view:
                state.current_view = state.previous_view
                state.previous_view = None
            return True
        elif key == "\r" or key == "\n":
            from .views.assessment_view import trigger_assessment_grading

            trigger_assessment_grading(state)
            return True
        elif key == "j":
            scroll = state.assessment_state.get("scroll_offset", 0)
            state.assessment_state["scroll_offset"] = scroll + 1
            return True
        elif key == "k":
            scroll = state.assessment_state.get("scroll_offset", 0)
            state.assessment_state["scroll_offset"] = max(0, scroll - 1)
            return True
        elif key == "f":
            from .views.assessment_view import trigger_fact_check

            trigger_fact_check(state)
            return True

    if key == "q":
        return False
    elif key == "c" or key == "\t":
        if state.current_view != View.CHAT:
            state.previous_view = state.current_view
            state.current_view = View.CHAT
    elif key == "\r" or key == "\n":
        if state.current_view == View.NOTEBOOK_LIST:
            state.previous_view = state.current_view
            state.current_view = View.NOTEBOOK_DETAIL
        elif state.current_view == View.NOTEBOOK_DETAIL:
            # Handle menu selection
            if state.detail_menu_index == 0:
                state.previous_view = state.current_view
                state.current_view = View.CHAT
            elif state.detail_menu_index == 1:
                from .views.notebook_detail import start_download

                start_download(state)
                state.previous_view = state.current_view
                state.current_view = View.NOTEBOOK_LIST
            elif state.detail_menu_index == 2:
                from .views.notebook_detail import start_source_selection

                start_source_selection(state)
            elif state.detail_menu_index == 3:
                from .views.notebook_detail import start_assess_audio_overview

                start_assess_audio_overview(state)
                state.previous_view = state.current_view
                state.current_view = View.NOTEBOOK_LIST
    elif key == "p":
        if state.current_view != View.COMPILER:
            state.previous_view = state.current_view
            state.current_view = View.COMPILER
    elif key == "A":
        if state.current_view != View.ASSESSMENT:
            state.previous_view = state.current_view
            state.current_view = View.ASSESSMENT
    elif key == "L":
        if state.current_view != View.LOGS:
            state.previous_view = state.current_view
            state.current_view = View.LOGS
    elif key == "n":
        # Jump back to the selected notebook from anywhere — c/p/A/L all jump
        # TO a view, but nothing jumped back to the notebook itself; Esc alone
        # can't do it reliably since previous_view is a single slot that gets
        # overwritten by the next c/p/A/L jump and is cleared after one use.
        target = View.NOTEBOOK_DETAIL if state.selected_notebook else View.NOTEBOOK_LIST
        if state.current_view != target:
            state.previous_view = state.current_view
            state.current_view = target
    elif key == "\x1b":  # Escape
        if state.previous_view:
            state.current_view = state.previous_view
            state.previous_view = None
    elif key == "s":
        state.sort_key = "modified" if state.sort_key == "name" else "name"
    elif key == "e" and state.current_view == View.NOTEBOOK_DETAIL and state.selected_notebook:
        state.editing_context = True
        state.context_edit_buffer = state.context_overrides.get(
            state.selected_notebook,
            state.notebook_summaries.get(state.selected_notebook, ""),
        )
    elif key in ("j", "k") and state.current_view == View.NOTEBOOK_DETAIL:
        if key == "j":
            state.detail_menu_index = min(state.detail_menu_index + 1, 3)
        else:
            state.detail_menu_index = max(state.detail_menu_index - 1, 0)
    elif key in ("j", "k") and state.notebooks:
        # Sort current notebooks to match view
        import datetime

        if state.sort_key == "name":
            notebooks = sorted(state.notebooks, key=lambda nb: getattr(nb, "title", "").lower())
        else:
            notebooks = sorted(
                state.notebooks,
                key=lambda nb: (
                    getattr(nb, "modified_at", None)
                    or getattr(nb, "created_at", None)
                    or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                ),
                reverse=True,
            )

        current_id = state.selected_notebook
        try:
            current_idx = next(i for i, nb in enumerate(notebooks) if nb.id == current_id)
        except StopIteration:
            current_idx = 0

        if key == "j":
            new_idx = min(current_idx + 1, len(notebooks) - 1)
            if new_idx >= state.scroll_offset + 15:
                state.scroll_offset = new_idx - 14
        else:
            new_idx = max(current_idx - 1, 0)
            if new_idx < state.scroll_offset:
                state.scroll_offset = new_idx

        state.selected_notebook = notebooks[new_idx].id
    return True
