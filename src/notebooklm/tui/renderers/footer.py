from rich.align import Align
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from ..state import TUIState


def render_footer(state: TUIState) -> Panel:
    hints = " [q] Quit | [c] Chat | [p] Compiler | [Tab] Focus | [j/k] Navigate "

    table = Table.grid(expand=True)
    table.add_column(justify="left", ratio=1)
    table.add_column(justify="right", ratio=1)

    left = Text(hints)

    from rich.console import RenderableType

    right: RenderableType

    if state.background_task and not state.background_task.done():
        right = Spinner("dots", text="Working...")
    elif state.error_message:
        right = Text(state.error_message, style="error")
    else:
        right = Text("Ready")

    table.add_row(left, right)

    return Panel(Align.center(table, vertical="middle"), style="footer", height=3)
