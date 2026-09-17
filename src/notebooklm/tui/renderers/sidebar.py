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

    # Ensure selected notebook is within viewport
    visible_rows = 15
    current_id = state.selected_notebook
    try:
        current_idx = next(i for i, nb in enumerate(notebooks) if nb.id == current_id)
    except StopIteration:
        current_idx = 0

    if current_idx < state.scroll_offset:
        state.scroll_offset = current_idx
    elif current_idx >= state.scroll_offset + visible_rows:
        state.scroll_offset = current_idx - visible_rows + 1

    # Slice notebooks for pagination
    notebooks = notebooks[state.scroll_offset : state.scroll_offset + visible_rows]

    for nb in notebooks:
        title = getattr(nb, "title", "Unknown")
        is_selected = nb.id == state.selected_notebook
        title = f"▶ {title}" if is_selected else f"  {title}"
        sources = str(getattr(nb, "sources_count", 0))
        mod_at = getattr(nb, "modified_at", None)
        modified = mod_at.strftime("%Y-%m-%d") if mod_at else "Unknown"

        is_selected = nb.id == state.selected_notebook
        style = "selected" if is_selected else ""

        # Explicitly style the text strings so Rich definitely renders the colors
        if is_selected:
            title = f"[{style}]{title}[/]"
            sources = f"[{style}]{sources}[/]"
            modified = f"[{style}]{modified}[/]"
        else:
            title = f"[foreground]{title}[/]"
            sources = f"[info]{sources}[/]"
            modified = f"[muted]{modified}[/]"

        table.add_row(title, sources, modified)

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
