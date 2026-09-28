from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ..state import TUIState
from ._widgets import key_hints

_GLOBAL_KEYS = [
    ("q", "quit"),
    ("c", "chat"),
    ("p", "compiler"),
    ("A", "assess"),
    ("L", "logs"),
    ("j/k", "move"),
    ("esc", "back"),
]


def render_footer(state: TUIState) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(justify="right", no_wrap=True)

    right: RenderableType
    progress = state.ingest_progress
    if state.background_task and not state.background_task.done() and progress.get("total_sources"):
        done = progress.get("done_sources", 0)
        total = progress.get("total_sources", 0)
        title = progress.get("current_title", "")
        label = f"Ingesting {done}/{total}"
        if title:
            label += f": {title[:32]}"
        right = Spinner("dots", text=Text(label, style="info"), style="info")
    elif state.background_task and not state.background_task.done():
        right = Spinner("dots", text=Text("Working", style="info"), style="info")
    elif state.error_message:
        msg = state.error_message
        right = Text(f"✗ {msg if len(msg) <= 60 else msg[:59] + '…'}", style="error")
    else:
        right = Text("● ready", style="success")

    table.add_row(key_hints(_GLOBAL_KEYS), right)

    return Panel(table, style="footer", border_style="border", box=box.ROUNDED, height=3)
