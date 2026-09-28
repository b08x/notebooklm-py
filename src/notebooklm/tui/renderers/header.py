from rich import box
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..state import TUIState


def _meter(tokens: int, max_tokens: int) -> Text:
    ratio = tokens / max_tokens if max_tokens else 0
    level = "success" if ratio > 0.5 else "warning" if ratio > 0.2 else "error"
    text = Text(no_wrap=True)
    text.append("API ", style="label")
    text.append("━" * tokens, style=level)
    text.append("━" * (max_tokens - tokens), style="subtle")
    text.append(f" {tokens}/{max_tokens}", style="muted")
    return text


def render_header(state: TUIState) -> Panel:
    state.update_tokens()  # Refresh tokens for display
    profile = "default"  # Could be pulled from env or config later
    view_name = state.current_view.name.replace("_", " ").title()

    left = Text(no_wrap=True, overflow="ellipsis")
    left.append("NotebookLM", style="heading")
    left.append("  /  ", style="subtle")
    left.append(view_name, style="foreground")
    left.append(f"   profile {profile}", style="muted")

    bar = Table.grid(expand=True)
    bar.add_column(ratio=1)
    bar.add_column(justify="right")
    bar.add_row(left, _meter(int(state.api_tokens), state.api_max_tokens))

    return Panel(bar, style="header", border_style="border", box=box.ROUNDED, height=3)
