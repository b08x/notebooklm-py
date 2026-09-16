from rich.align import Align
from rich.panel import Panel

from ..state import TUIState, View
from .chat import render_chat
from .compiler import render_compiler


def render_main(state: TUIState) -> Panel:
    if state.current_view == View.CHAT:
        return render_chat(state)
    elif state.current_view == View.COMPILER:
        return render_compiler(state)

    content = f"Placeholder for {state.current_view.name}"

    if state.current_view == View.NOTEBOOK_LIST:
        content = "Select a notebook from the sidebar."

    return Panel(
        Align.center(content, vertical="middle"),
        title=state.current_view.name.replace("_", " ").title(),
        border_style="border",
        style="main",
    )
