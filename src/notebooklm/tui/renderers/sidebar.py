from rich.panel import Panel
from rich.tree import Tree

from ..state import TUIState


def render_sidebar(state: TUIState) -> Panel:
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

    tree = Tree("📚 [b]Notebooks[/b]")

    for nb in notebooks:
        title = getattr(nb, "title", "Unknown")
        is_selected = nb.id == state.selected_notebook
        sources = str(getattr(nb, "sources_count", 0))

        style = "selected" if is_selected else "foreground"
        prefix = "▶" if is_selected else " "
        node_label = f"[{style}]{prefix} {title} ({sources} sources)[/]"

        tree.add(node_label)

    if not state.notebooks:
        tree.add("[muted]No notebooks found.[/]")

    tree.add("")
    commands = tree.add("⚙️  [b]Commands[/b]")
    commands.add("[Enter] Select")
    commands.add("[c] Chat")
    commands.add("[p] Prompt Compiler")
    commands.add("[s] Sort Notebooks")
    commands.add("[A] Assessment")
    commands.add("[r] Refresh")
    commands.add("[q] Quit")

    return Panel(tree, title="Corpus & Actions", border_style="border")
