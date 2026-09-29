from rich.console import RenderableType

from notebooklm.tui.renderers import (
    render_footer,
    render_header,
    render_main,
    render_sidebar,
)
from notebooklm.tui.renderers.chat import render_chat
from notebooklm.tui.renderers.compiler import render_compiler
from notebooklm.tui.state import TUIState, View


def test_render_header():
    state = TUIState()
    result = render_header(state)
    assert isinstance(result, RenderableType)


def test_render_sidebar():
    state = TUIState()
    result = render_sidebar(state)
    assert isinstance(result, RenderableType)


def test_render_main():
    state = TUIState()
    results = render_main(state)
    if not isinstance(results, tuple):
        results = (results,)
    for result in results:
        assert isinstance(result, RenderableType)


def test_render_footer():
    state = TUIState()
    result = render_footer(state)
    assert isinstance(result, RenderableType)


def test_render_chat():
    state = TUIState()
    state.current_view = View.CHAT
    results = render_chat(state)
    for result in results:
        assert isinstance(result, RenderableType)


def test_render_compiler():
    state = TUIState()
    state.current_view = View.COMPILER
    results = render_compiler(state)
    for result in results:
        assert isinstance(result, RenderableType)


def test_full_layout_render_no_crash():
    import io

    from rich.console import Console

    from notebooklm.tui.app import build_layout, update_layout
    from notebooklm.tui.theme import THEME

    state = TUIState()
    layout = build_layout()
    update_layout(layout, state)

    # We must use THEME here to ensure all styles referenced by the components are resolved
    console = Console(theme=THEME, file=io.StringIO(), force_terminal=True)
    # This will raise a MissingStyle exception if any component uses an undeclared style
    console.print(layout)

    output = console.file.getvalue()
    assert len(output) > 0


# --- curation modal panels ------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from notebooklm._app.archive import VerifyResult  # noqa: E402
from notebooklm._app.curation import CurationItem  # noqa: E402
from notebooklm.tui.renderers.main import _render_curation  # noqa: E402


def _render_text(renderables) -> str:
    import io

    from rich.console import Console

    from notebooklm.tui.theme import THEME

    if not isinstance(renderables, (tuple, list)):
        renderables = (renderables,)
    # NB: force_terminal=True makes this rich build ignore an explicit width,
    # and the curation hint line needs more than the default 80 columns.
    console = Console(theme=THEME, file=io.StringIO(), width=160)
    for renderable in renderables:
        console.print(renderable)
    return console.file.getvalue()


def _curation_state(curation: dict) -> TUIState:
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    state.curation = curation
    return state


def test_render_curation_items_list_shows_titles_and_mark_state():
    curation = {
        "mode": "items",
        "items": [
            CurationItem("source", "src-1", "Redundant paper"),
            CurationItem("note", "note-1", "Hallucinated note"),
        ],
        "cursor": 0,
        "marked": {"note-1"},
        "loading": False,
    }
    text = _render_text(_render_curation(_curation_state(curation)))
    assert "Redundant paper" in text
    assert "Hallucinated note" in text
    assert "1 marked" in text


def test_render_curation_confirm_lists_marked_titles():
    curation = {
        "mode": "confirm_yn",
        "items": [
            CurationItem("source", "src-1", "Redundant paper"),
            CurationItem("artifact", "art-1", "Wrong report"),
        ],
        "marked": {"art-1"},
    }
    text = _render_text(_render_curation(_curation_state(curation)))
    assert "Wrong report" in text
    assert "Redundant paper" not in text
    assert "Remove all marked items?" in text


def test_render_curation_reason_lists_all_five_options():
    curation = {"mode": "reason", "pending": "remove"}
    text = _render_text(_render_curation(_curation_state(curation)))
    for reason in ("redundant", "incorrect", "experimental", "hallucinated", "other"):
        assert reason in text


def test_render_curation_add_source_prompts():
    text = _render_text(_render_curation(_curation_state({"mode": "add_kind"})))
    assert "URL" in text and "Local file" in text and "Pasted text" in text

    text = _render_text(
        _render_curation(
            _curation_state({"mode": "add_input", "add_kind": "url", "buffer": "https://"})
        )
    )
    assert "https://" in text


def test_render_curation_typed_confirm_shows_title():
    curation = {
        "mode": "typed_confirm",
        "pending": "delete_notebook",
        "notebook_title": "Test Notebook",
        "buffer": "test",
    }
    text = _render_text(_render_curation(_curation_state(curation)))
    assert "Test Notebook" in text


def test_render_curation_archive_progress_shows_done_over_total():
    curation = {"mode": "archive_progress", "archive": {"done": 2, "total": 5}}
    text = _render_text(_render_curation(_curation_state(curation)))
    assert "2/5" in text


def test_render_curation_archive_result_shows_verification_and_failures():
    result = SimpleNamespace(
        verify=VerifyResult(
            ok=False, file_count=7, total_bytes=2048, missing=["sources/lost.md"], empty=[]
        ),
        failed_items=[
            {
                "id": "art-1",
                "title": "Broken report",
                "error": "download exploded",
                "status": "failed",
            }
        ],
        final_path=None,
        partial_path=SimpleNamespace(name="nb.tar.gz.partial"),
    )
    curation = {"mode": "archive_result", "archive_result": result, "notice": "Archive incomplete"}
    text = _render_text(_render_curation(_curation_state(curation)))
    assert "7 files" in text
    assert "2.0 KB" in text
    assert "Broken report" in text
    assert "download exploded" in text
    assert "sources/lost.md" in text


def test_render_curation_shows_error_and_notice():
    curation = {
        "mode": "items",
        "items": [CurationItem("source", "src-1", "S")],
        "marked": set(),
        "notice": "Removed 1 item(s) (redundant). Failed: Broken report.",
        "error": "No items marked — move with j/k and mark with Space.",
    }
    text = _render_text(_render_curation(_curation_state(curation)))
    assert "Failed: Broken report." in text
    assert "No items marked" in text


def test_render_curation_closed_returns_none():
    state = TUIState()
    assert _render_curation(state) is None


def test_render_main_routes_curation_modal():
    state = _curation_state({"mode": "reason", "pending": "remove"})
    panels = render_main(state)
    assert isinstance(panels, tuple)
    text = _render_text(panels)
    assert "redundant" in text


def test_render_footer_shows_curation_keys_in_notebook_detail():
    state = TUIState()
    state.current_view = View.NOTEBOOK_DETAIL
    state.selected_notebook = "nb-1"
    text = _render_text(render_footer(state))
    for key, label in (
        ("m", "mark items"),
        ("x", "remove marked"),
        ("+", "add source"),
        ("D", "delete nb"),
        ("X", "archive nb"),
    ):
        assert f"{key} {label}" in text


def test_render_footer_hides_curation_keys_outside_notebook_detail():
    state = TUIState()
    state.current_view = View.NOTEBOOK_LIST
    text = _render_text(render_footer(state))
    assert "mark items" not in text


def test_render_ingest_picker_tags_notes():
    state = TUIState()
    state.selecting_sources = True
    note = SimpleNamespace(id="note-1", kind="note", title="Meeting note")
    src = SimpleNamespace(id="src-1", kind="source", title="A source")
    state.ingest_sources = [src, note]
    state.ingest_selected = {"note-1"}
    state.ingest_cursor = 0
    text = _render_text(render_main(state))
    assert "[note] Meeting note" in text
    assert "A source" in text
