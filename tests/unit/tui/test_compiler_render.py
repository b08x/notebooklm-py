"""Renderer tests for the Compiler view (facts 4, 5, 9, 15, 16)."""

from __future__ import annotations

import io

from rich.console import RenderableType

from notebooklm.tui.renderers.compiler import (
    _render_preview_header,
    char_count_style,
    format_elapsed,
    render_compiler,
)
from notebooklm.tui.renderers.footer import render_footer
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.theme import THEME


def _render_text(renderables) -> str:
    from rich.console import Console

    if not isinstance(renderables, (tuple, list)):
        renderables = (renderables,)
    console = Console(theme=THEME, file=io.StringIO(), width=160)
    for renderable in renderables:
        console.print(renderable)
    return console.file.getvalue()


def _compiler_state(**overrides) -> TUIState:
    state = TUIState()
    state.current_view = View.COMPILER
    state.selected_notebook = "nb-1"
    state.compiler_state = {
        "configs": [],
        "selected_config": 0,
        "phase": "compiled",
        "prompt": "COMPILED PROMPT BODY",
        "edited": False,
        "project": "sfl-engine-pipeline-mechanics",
        "notebook_id": "nb-1",
        "notebook_title": "SFL Notebook",
        "audio_format": "deep-dive",
        "audio_length": "default",
        "scroll": 0,
        **overrides,
    }
    return state


def test_compiler_view_renders_panels():
    state = _compiler_state()
    results, detail = render_compiler(state)
    assert isinstance(results, RenderableType)
    assert isinstance(detail, RenderableType)


def test_header_includes_project_notebook_format_length_and_chars():
    state = _compiler_state()
    text = _render_text(_render_preview_header(state))
    assert "sfl-engine-pipeline-mechanics" in text
    assert "SFL Notebook" in text
    assert "deep-dive" in text
    assert "default" in text
    assert f"{len(state.compiler_state['prompt'])} chars" in text


def test_char_count_warning_style_threshold():
    """Warning above 5,000 characters; not a warning at exactly 5,000 (fact 5)."""
    assert char_count_style(5000) == "muted"
    assert char_count_style(5001) == "warning"

    state = _compiler_state(prompt="x" * 5000)
    assert "warning" not in _style_names(_render_preview_header(state))
    state = _compiler_state(prompt="x" * 5001)
    assert "warning" in _style_names(_render_preview_header(state))


def _style_names(header) -> set[str]:
    """Styles carried by the header Text's spans."""
    return {str(span.style) for span in header._spans}  # noqa: SLF001 - test-only introspection


def test_edited_chip_appears_in_header():
    state = _compiler_state(edited=True)
    text = _render_text(_render_preview_header(state))
    assert "edited" in text


def test_evidence_section_shows_slot_clauses():
    state = _compiler_state(
        evidence={"agreement": [("c-1", "checkpoint clause text")], "confusion": []}
    )
    rendered = _render_text(render_compiler(state)[1])
    assert "Evidence" in rendered
    assert "agreement ← c-1" in rendered


def test_confirm_panel_lists_fields_and_keys():
    state = _compiler_state(confirm=True, edited=True)
    rendered = _render_text(render_compiler(state)[1])
    assert "Send this prompt to NotebookLM?" in rendered
    assert "SFL Notebook" in rendered
    assert "sfl-engine-pipeline-mechanics" in rendered
    assert "deep-dive" in rendered
    assert "default" in rendered
    assert "chars" in rendered
    assert "edited" in rendered
    assert "y send" in rendered
    assert "n cancel" in rendered


def test_failed_status_shows_error_and_artifact():
    state = _compiler_state(phase="failed", error="rate limited", artifact_id="art-123")
    rendered = _render_text(render_compiler(state)[1])
    assert "failed" in rendered
    assert "rate limited" in rendered
    assert "art-123" in rendered


def test_done_status_shows_mp3_path():
    state = _compiler_state(phase="done", mp3_path="/tmp/audio/x.mp3")
    rendered = _render_text(render_compiler(state)[1])
    assert "/tmp/audio/x.mp3" in rendered


def test_target_notebook_line_in_config_list():
    state = _compiler_state()
    rendered = _render_text(render_compiler(state)[0])
    assert "→ SFL Notebook" in rendered

    state = TUIState()
    state.current_view = View.COMPILER
    state.compiler_state = {"configs": [], "selected_config": 0}
    rendered = _render_text(render_compiler(state)[0])
    assert "no notebook selected" in rendered


def test_footer_shows_compiler_hints():
    state = _compiler_state()
    rendered = _render_text(render_footer(state))
    for hint in ("enter compile", "e edit", "g generate", "j/k scroll", "esc back"):
        assert hint in rendered


def test_format_elapsed():
    assert format_elapsed(None) == "00:00"
    assert format_elapsed(100.0, now=100.0) == "00:00"
    assert format_elapsed(100.0, now=160.0) == "01:00"
    assert format_elapsed(100.0, now=100.0 + 125.0) == "02:05"


def test_warning_line_shown_for_fallback():
    state = _compiler_state(
        warning="No ingested clauses found — slots filled via NotebookLM chat fallback."
    )
    rendered = _render_text(render_compiler(state)[1])
    assert "chat fallback" in rendered
