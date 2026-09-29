from rich import box
from rich.console import RenderableType
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ..state import TUIState, View
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

#: Curation keys shown while Notebook Detail is active (fact 16).
_CURATION_KEYS = [
    ("m", "mark items"),
    ("x", "remove marked"),
    ("+", "add source"),
    ("D", "delete nb"),
    ("X", "archive nb"),
]

#: Compiler-view keys (fact 16): compile, edit, generate, scroll, back.
_COMPILER_KEYS = [
    ("enter", "compile"),
    ("e", "edit"),
    ("g", "generate"),
    ("j/k", "scroll"),
    ("esc", "back"),
]


def render_footer(state: TUIState) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_column(justify="right", no_wrap=True)

    left_keys = _GLOBAL_KEYS
    if state.current_view == View.NOTEBOOK_DETAIL:
        left_keys = _GLOBAL_KEYS + _CURATION_KEYS
    elif state.current_view == View.COMPILER:
        left_keys = _COMPILER_KEYS

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

    table.add_row(key_hints(left_keys), right)

    return Panel(table, style="footer", border_style="border", box=box.ROUNDED, height=3)
