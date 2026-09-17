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
