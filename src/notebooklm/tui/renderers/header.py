from rich.align import Align
from rich.panel import Panel

from ..state import TUIState


def render_header(state: TUIState) -> Panel:
    profile = "default"  # Could be pulled from env or config later
    view_name = state.current_view.name.replace("_", " ").title()
    content = f"NotebookLM | Profile: {profile} | View: {view_name}"

    return Panel(Align.center(content, vertical="middle"), style="header", height=3)
