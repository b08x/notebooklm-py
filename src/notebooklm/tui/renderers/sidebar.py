from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from ..state import TUIState


def render_sidebar_notebooks(state: TUIState) -> Panel:
    table = Table(show_header=True, expand=True, show_edge=False, box=None)
    table.add_column("Name")
    table.add_column("Sources", justify="right")
    table.add_column("Modified", justify="right")

    import datetime

    if state.sort_key == "name":
        notebooks = sorted(state.notebooks, key=lambda nb: getattr(nb, "title", "").lower())
    elif state.sort_key == "modified":
        notebooks = sorted(
            state.notebooks,
            key=lambda nb: (
                getattr(nb, "modified_at", None)
                or getattr(nb, "created_at", None)
                or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
            ),
            reverse=True,
        )
    else:
        notebooks = state.notebooks

    for nb in notebooks:
        title = getattr(nb, "title", "Unknown")
        sources = str(getattr(nb, "sources_count", 0))
        mod_at = getattr(nb, "modified_at", None)
        modified = mod_at.strftime("%Y-%m-%d") if mod_at else "Unknown"

        is_selected = nb.id == state.selected_notebook
        style = "selected" if is_selected else ""

        # If not selected, apply the colors to the cells directly
        if not is_selected:
            title = f"[foreground]{title}[/]"
            sources = f"[info]{sources}[/]"
            modified = f"[muted]{modified}[/]"

        table.add_row(title, sources, modified, style=style)

    if not state.notebooks:
        table.add_row("No notebooks found.", "", "")

    return Panel(table, title="Notebooks", border_style="border")


def render_sidebar_commands(state: TUIState) -> Panel:
    tree = Tree("Commands")
    tree.add("[Enter] Select")
    tree.add("[c] Chat")
    tree.add("[p] Prompt Compiler")
    tree.add("[s] Sort Notebooks")
    tree.add("[r] Refresh")
    tree.add("[q] Quit")

    return Panel(tree, title="Actions", border_style="border")
