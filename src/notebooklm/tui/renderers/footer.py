from rich.align import Align
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ..state import TUIState


def render_footer(state: TUIState) -> Panel:
    hints = (
        " [q] Quit | [n] Notebook | [c] Chat | [p] Compiler | [A] Assess | [L] Logs | "
        "[Tab] Focus | [j/k] Navigate | [Esc] Back "
    )

    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right", ratio=1)

    left = Text(hints)

    from rich.console import RenderableType

    right: RenderableType

    progress = state.ingest_progress
    if state.background_task and not state.background_task.done() and progress.get("total_sources"):
        done = progress.get("done_sources", 0)
        total = progress.get("total_sources", 0)
        title = progress.get("current_title", "")
        label = f"Ingesting {done}/{total}"
        if title:
            label += f": {title}"
        right = Spinner("dots", text=label)
    elif state.background_task and not state.background_task.done():
        right = Spinner("dots", text="Working...")
    elif state.error_message:
        right = Text(state.error_message, style="error")
    else:
        right = Text("Ready")

    table.add_row(left, right)

    return Panel(Align.center(table, vertical="middle"), style="footer", height=3)
