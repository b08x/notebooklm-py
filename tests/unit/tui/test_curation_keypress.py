"""Key-dispatch tests for the curation modal (``tui/keypress.py``)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import notebooklm.tui.views.curation_view as curation_view
from notebooklm._app.curation import CurationItem
from notebooklm.tui.keypress import handle_key
from notebooklm.tui.state import TUIState, View

ITEMS = [
    CurationItem("source", "src-1", "First source"),
    CurationItem("artifact", "art-1", "A report"),
    CurationItem("note", "note-1", "A note"),
]


def _open_items_modal(state: TUIState, items: list[CurationItem] = ITEMS) -> None:
    state.curation = {
        "mode": "items",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "items": list(items),
        "cursor": 0,
        "marked": set(),
        "loading": False,
        "error": None,
        "notice": None,
    }


@pytest.fixture()
def notebook_state() -> TUIState:
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    state.notebooks = [MagicMock(id="nb-1", title="Test Notebook")]
    return state


@pytest.fixture()
def workers(monkeypatch: pytest.MonkeyPatch) -> dict[str, MagicMock]:
    """Replace every curation worker starter with a recording mock."""
    mocks = {
        name: MagicMock()
        for name in (
            "start_curation_list",
            "start_remove_items",
            "start_add_source",
            "start_notebook_delete",
            "start_archive",
            "start_archive_delete",
            "start_add_source_modal",
            "start_notebook_delete_modal",
            "start_archive_modal",
        )
    }
    for name, mock in mocks.items():
        monkeypatch.setattr(curation_view, name, mock)
    mocks["start_curation_list"].side_effect = _open_items_modal
    return mocks


# --- opening the modal ---------------------------------------------------------


def test_m_opens_curation_list_in_notebook_detail(notebook_state, workers) -> None:
    assert handle_key("m", notebook_state) is True
    workers["start_curation_list"].assert_called_once()
    assert notebook_state.curation["mode"] == "items"


def test_curation_keys_are_inactive_outside_notebook_detail(workers) -> None:
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    for key in ("m", "+", "D", "X"):
        handle_key(key, state)
    assert state.curation == {}


def test_plus_opens_add_source_modal(notebook_state, workers) -> None:
    handle_key("+", notebook_state)
    workers["start_add_source_modal"].assert_called_once_with(notebook_state)


def test_D_and_X_open_reason_modals(notebook_state, workers) -> None:
    handle_key("D", notebook_state)
    workers["start_notebook_delete_modal"].assert_called_once_with(notebook_state)
    handle_key("X", notebook_state)
    workers["start_archive_modal"].assert_called_once_with(notebook_state)


# --- mark list ------------------------------------------------------------------


def test_mark_and_unmark_with_space(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    assert handle_key(" ", notebook_state) is True
    assert notebook_state.curation["marked"] == {"src-1"}
    assert handle_key(" ", notebook_state) is True
    assert notebook_state.curation["marked"] == set()


def test_j_moves_cursor(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key("j", notebook_state)
    assert notebook_state.curation["cursor"] == 1
    handle_key("k", notebook_state)
    assert notebook_state.curation["cursor"] == 0


def test_x_without_marks_shows_error_and_dispatches_nothing(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key("x", notebook_state)
    assert notebook_state.curation["mode"] == "items"
    assert notebook_state.curation["error"]
    workers["start_remove_items"].assert_not_called()


def test_confirm_yn_lists_marked_items_then_y_goes_to_reason(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key(" ", notebook_state)  # mark src-1
    handle_key("x", notebook_state)
    assert notebook_state.curation["mode"] == "confirm_yn"

    # 'N' or Escape cancels and nothing is removed (fact 2).
    handle_key("N", notebook_state)
    assert notebook_state.curation["mode"] == "items"
    workers["start_remove_items"].assert_not_called()

    handle_key("x", notebook_state)
    handle_key("\x1b", notebook_state)  # Escape also cancels
    assert notebook_state.curation["mode"] == "items"

    handle_key("x", notebook_state)
    handle_key("y", notebook_state)
    assert notebook_state.curation["mode"] == "reason"
    assert notebook_state.curation["pending"] == "remove"


# --- reason picker ----------------------------------------------------------------


def test_reason_key_dispatches_removal_with_selected_items(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key(" ", notebook_state)  # mark src-1
    handle_key("j", notebook_state)
    handle_key(" ", notebook_state)  # mark art-1
    handle_key("x", notebook_state)
    handle_key("y", notebook_state)

    assert handle_key("2", notebook_state) is True
    workers["start_remove_items"].assert_called_once()
    items, reason = workers["start_remove_items"].call_args[0][1:]
    assert [item.id for item in items] == ["src-1", "art-1"]
    assert reason == "incorrect"


def test_reason_mode_ignores_keys_other_than_one_to_five(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key(" ", notebook_state)
    handle_key("x", notebook_state)
    handle_key("y", notebook_state)
    handle_key("9", notebook_state)
    handle_key("r", notebook_state)
    workers["start_remove_items"].assert_not_called()
    assert notebook_state.curation["mode"] == "reason"


def test_delete_notebook_reason_leads_to_typed_confirm(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "reason",
        "pending": "delete_notebook",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "items": [],
        "error": None,
    }
    handle_key("3", notebook_state)
    assert notebook_state.curation["mode"] == "typed_confirm"
    assert notebook_state.curation["reason"] == "experimental"
    workers["start_notebook_delete"].assert_not_called()


def test_archive_reason_dispatches_archive_worker(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "reason",
        "pending": "archive",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "items": [],
        "error": None,
    }
    handle_key("1", notebook_state)
    workers["start_archive"].assert_called_once_with(notebook_state, "redundant")


# --- add source --------------------------------------------------------------------


def test_add_kind_selection_and_input_buffer(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "add_kind",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "error": None,
    }
    handle_key("u", notebook_state)
    assert notebook_state.curation["mode"] == "add_input"
    assert notebook_state.curation["add_kind"] == "url"

    for ch in "https://example.com":
        handle_key(ch, notebook_state)
    assert notebook_state.curation["buffer"] == "https://example.com"

    handle_key("\x7f", notebook_state)
    assert notebook_state.curation["buffer"] == "https://example.co"

    handle_key("\r", notebook_state)
    workers["start_add_source"].assert_called_once()
    args = workers["start_add_source"].call_args[0]
    assert args[1] == "url" and args[2] == "https://example.co"


def test_invalid_file_path_shows_error_and_sends_no_request(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "add_kind",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "error": None,
    }
    handle_key("f", notebook_state)
    for ch in "/definitely/not/a/file.txt":
        handle_key(ch, notebook_state)
    handle_key("\r", notebook_state)

    assert notebook_state.curation["error"]
    workers["start_add_source"].assert_not_called()
    assert notebook_state.curation["mode"] == "add_input"


def test_empty_url_input_is_rejected(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "add_input",
        "add_kind": "url",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "buffer": "ftp://nope",
        "error": None,
    }
    handle_key("\r", notebook_state)
    assert notebook_state.curation["error"]
    workers["start_add_source"].assert_not_called()


# --- typed confirmation --------------------------------------------------------------


def test_typed_title_mismatch_blocks_notebook_delete(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "typed_confirm",
        "pending": "delete_notebook",
        "reason": "incorrect",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "buffer": "",
        "error": None,
    }
    for ch in "nope":
        handle_key(ch, notebook_state)
    handle_key("\r", notebook_state)

    assert notebook_state.curation["error"]
    workers["start_notebook_delete"].assert_not_called()
    assert notebook_state.curation["mode"] == "typed_confirm"


def test_typed_title_match_dispatches_notebook_delete(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "typed_confirm",
        "pending": "delete_notebook",
        "reason": "incorrect",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "buffer": "",
        "error": None,
    }
    for ch in "test note":
        handle_key(ch, notebook_state)
    handle_key("\r", notebook_state)

    workers["start_notebook_delete"].assert_called_once_with(notebook_state, "incorrect")


def test_typed_title_match_dispatches_archive_delete(notebook_state, workers) -> None:
    notebook_state.curation = {
        "mode": "typed_confirm",
        "pending": "archive_delete",
        "notebook_id": "nb-1",
        "notebook_title": "Test Notebook",
        "buffer": "",
        "error": None,
    }
    for ch in "Test Notebook":
        handle_key(ch, notebook_state)
    handle_key("\r", notebook_state)

    workers["start_archive_delete"].assert_called_once_with(notebook_state, "Test Notebook")


def test_escape_closes_the_curation_modal(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key("\x1b", notebook_state)
    assert notebook_state.curation == {}


def test_q_quits_even_inside_the_modal(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    assert handle_key("q", notebook_state) is False


def test_modal_captures_regular_notebook_detail_keys(notebook_state, workers) -> None:
    _open_items_modal(notebook_state)
    handle_key("e", notebook_state)
    assert notebook_state.editing_context is False


# --- post-delete sidebar ---------------------------------------------------------------


def test_deleted_notebook_disappears_from_sidebar(notebook_state) -> None:
    other = MagicMock(id="nb-2", title="Keeper")
    notebook_state.notebooks.append(other)
    assert len(notebook_state.get_filtered_and_sorted_notebooks()) == 2

    curation_view._forget_notebook(notebook_state, "nb-1")

    visible = notebook_state.get_filtered_and_sorted_notebooks()
    assert [nb.id for nb in visible] == ["nb-2"]
    assert notebook_state.current_view == View.NOTEBOOK_LIST


def test_curation_modal_openers_require_selected_notebook() -> None:
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = None
    for opener in (
        curation_view.start_curation_list,
        curation_view.start_add_source_modal,
        curation_view.start_notebook_delete_modal,
        curation_view.start_archive_modal,
    ):
        opener(state)  # must be a no-op, not a crash
    assert state.curation == {}
    assert state.curation_task is None
