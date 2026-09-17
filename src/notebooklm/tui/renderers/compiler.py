from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from ..state import TUIState
from ..views.compiler_view import load_compiler_configs


def render_compiler(state: TUIState) -> tuple[Panel, Panel]:
    if "configs" not in state.compiler_state:
        load_compiler_configs(state)

    configs = state.compiler_state.get("configs", [])
    selected_idx = state.compiler_state.get("selected_config", 0)

    table = Table(title="Projects", show_header=False, expand=True)
    table.add_column("Project")

    for i, config in enumerate(configs):
        style = "reverse" if i == selected_idx else ""
        table.add_row(
            f"[{'V' if 'notebooklm-video' in str(config) else 'A'}] {config.name}", style=style
        )

    if not configs:
        table.add_row("No YAML configurations found.")

    results_panel = Panel(table, title="Compiler Configs", border_style="border", style="main")

    preview_text = state.compiler_state.get(
        "preview", "Press Enter to compile the selected project."
    )
    detail_panel = Panel(
        Syntax(preview_text, "markdown", word_wrap=True, theme="monokai"),
        title="Preview / Output",
        border_style="border",
        style="main",
    )

    return results_panel, detail_panel
