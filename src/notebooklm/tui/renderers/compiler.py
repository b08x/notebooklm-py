from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..state import TUIState
from ..theme import COLORS
from ..views.compiler_view import load_compiler_configs
from ._widgets import panel


def render_compiler(state: TUIState) -> tuple[Panel, Panel]:
    if "configs" not in state.compiler_state:
        load_compiler_configs(state)

    configs = state.compiler_state.get("configs", [])
    selected_idx = state.compiler_state.get("selected_config", 0)

    table = Table.grid(expand=True)
    table.add_column(width=2, no_wrap=True)
    table.add_column(width=6, no_wrap=True)
    table.add_column(ratio=1, no_wrap=True, overflow="ellipsis")

    for i, config in enumerate(configs):
        is_selected = i == selected_idx
        kind = "video" if "notebooklm-video" in str(config) else "audio"
        table.add_row(
            Text("▌" if is_selected else " ", style="marker"),
            Text(kind, style="label"),
            Text(config.name),
            style="selected" if is_selected else "foreground",
        )

    if not configs:
        table.add_row("", "", Text("No YAML configurations found.", style="muted"))

    results_panel = panel(table, "Compiler Configs", focused=True)

    preview_text = state.compiler_state.get(
        "preview", "Press Enter to compile the selected project."
    )
    detail_panel = panel(
        # Match the panel background so the code block does not render as a
        # differently colored slab inside the pane.
        Syntax(
            preview_text,
            "markdown",
            word_wrap=True,
            theme="monokai",
            background_color=COLORS["background"],
        ),
        "Preview",
    )

    return results_panel, detail_panel
