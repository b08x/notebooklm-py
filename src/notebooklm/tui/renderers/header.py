from rich.align import Align
from rich.panel import Panel

from ..state import TUIState


def render_header(state: TUIState) -> Panel:
    state.update_tokens()  # Refresh tokens for display
    profile = "default"  # Could be pulled from env or config later
    view_name = state.current_view.name.replace("_", " ").title()

    # Meter visualization
    tokens = int(state.api_tokens)
    meter = f"[{'█' * tokens}{'░' * (state.api_max_tokens - tokens)}]"

    content = f"NotebookLM | Profile: {profile} | View: {view_name} | API: {meter} {tokens}/{state.api_max_tokens}"

    return Panel(Align.center(content, vertical="middle"), style="header", height=3)
