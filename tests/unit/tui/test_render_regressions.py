"""Regression tests for rendering glitches: swallowed key hints, tail clipping,
sidebar overflow, and markup injection from user data."""

import io
from types import SimpleNamespace

from rich.console import Console
from rich.layout import Layout

from notebooklm.tui.app import build_layout, update_layout
from notebooklm.tui.renderers import render_footer, render_sidebar
from notebooklm.tui.renderers.chat import render_chat
from notebooklm.tui.renderers.logs import render_logs
from notebooklm.tui.state import TUIState, View
from notebooklm.tui.theme import THEME
from notebooklm.tui.views.assessment_view import AssessmentView
from notebooklm.tui.views.visual_assessment_view import VisualAssessmentView


def _render(renderable, width: int = 100, height: int | None = None) -> str:
    console = Console(theme=THEME, width=width, record=True, file=io.StringIO())
    if height is not None:
        console.print(Layout(renderable), height=height)
    else:
        console.print(renderable)
    return console.export_text()


def test_footer_lowercase_key_hints_are_visible():
    # "[c] Chat" as Rich markup is parsed as a style tag and vanishes.
    output = _render(render_footer(TUIState()), width=140)
    for hint in ("q quit", "c chat", "p compiler", "j/k move"):
        assert hint in output


def test_logs_show_newest_lines_when_buffer_exceeds_pane():
    state = TUIState()
    for i in range(100):
        state.log_records.append(("INFO", f"line-{i:03d}"))
    logs_panel, _ = render_logs(state)
    output = _render(logs_panel, height=12)
    assert "line-099" in output
    assert "line-000" not in output


def test_chat_shows_latest_message_when_history_exceeds_pane():
    state = TUIState()
    state.chat_history = [{"role": "user", "text": f"question {i}"} for i in range(40)]
    history, _ = render_chat(state)
    output = _render(history, height=12)
    assert "question 39" in output
    assert "question 0\n" not in output


def test_sidebar_fits_height_and_keeps_selection_visible():
    state = TUIState()
    state.notebooks = [
        SimpleNamespace(id=f"nb-{i:02d}", title=f"Notebook {i:02d}", sources_count=i)
        for i in range(40)
    ]
    state.selected_notebook = "nb-30"
    output = _render(render_sidebar(state), width=50, height=20)
    lines = output.splitlines()
    assert len(lines) == 20
    assert "Notebook 30" in output
    assert "s sort" in output  # list keys stay pinned at the bottom
    assert state.sidebar_rows == 20 - 2 - 5


def test_sidebar_long_title_is_truncated_not_wrapped():
    state = TUIState()
    state.notebooks = [SimpleNamespace(id="a", title="x" * 200, sources_count=7)]
    state.selected_notebook = "a"
    output = _render(render_sidebar(state), width=40, height=12)
    row = next(line for line in output.splitlines() if "xxx" in line)
    assert "…" in row
    assert row.rstrip("│ ").endswith("7")


def test_assessment_tolerates_markup_in_user_data():
    state = TUIState()
    state.assessment_state = {
        "audio_metadata": "[/] closing tag [bold]",
        "system_instructions": "[red]not a style[/red]",
        "chunks": ["Chunk 1"],
        "llm_score": "[/nope]",
    }
    left, _ = AssessmentView(state).render()
    output = _render(left)
    assert "[/] closing tag [bold]" in output
    assert "[red]not a style[/red]" in output


def test_assessment_hitl_prompt_tolerates_markup_in_chunk():
    state = TUIState()
    state.assessment_state = {
        "is_loading": True,
        "metrics": {"completed": 1, "total": 2, "passed": 1, "failed": 0},
        "hitl_prompt": {"chunk": "host says [/] and [laughs]"},
    }
    dash, _ = AssessmentView(state).render()
    output = _render(dash, width=140, height=30)
    assert "[laughs]" in output
    assert "CONFIDENCE" not in output


def test_visual_assessment_tolerates_markup_in_file_names():
    state = TUIState()
    state.assessment_state = {"results": [{"file": "[/]img.png", "status": "classified"}]}
    _, right = VisualAssessmentView(state).render()
    assert "[/]img.png" in _render(right)


def test_full_layout_renders_every_view():
    for view in View:
        state = TUIState()
        state.current_view = view
        layout = build_layout()
        update_layout(layout, state)
        console = Console(theme=THEME, width=120, height=40, file=io.StringIO())
        console.print(layout)
