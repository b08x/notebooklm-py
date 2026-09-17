from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState, View
from ..views.notebook_detail import fetch_summary_if_needed
from .chat import render_chat
from .compiler import render_compiler


def render_main(state: TUIState) -> Panel:
    if state.current_view == View.CHAT:
        return render_chat(state)
    elif state.current_view == View.COMPILER:
        return render_compiler(state)
    elif state.current_view == View.ASSESSMENT:
        from ..views.assessment_view import AssessmentView
        return AssessmentView(state)

    if state.current_view == View.NOTEBOOK_DETAIL:
        if not state.selected_notebook:
            return Panel(
                Align.center("No notebook selected.", vertical="middle"),
                title="Notebook Actions",
                border_style="border",
                style="main",
            )

        nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
        title = getattr(nb, "title", "Unknown Notebook") if nb else "Unknown Notebook"

        menu_items = ["1. Chat with Notebook", "2. Download Assets (Sources, Overviews)"]

        # Render the menu

        menu_text = Text()
        for i, item in enumerate(menu_items):
            if i == state.detail_menu_index:
                menu_text.append(f"▶ {item}\n", style="selected")
            else:
                menu_text.append(f"  {item}\n", style="foreground")

        title_text = Text(title, style="bold primary", justify="center")

        content_group = Group(
            Align.center(title_text),
            Text("\nWhat would you like to do?\n", justify="center", style="info"),
            Align.center(menu_text),
        )

        return Panel(
            content_group,
            title="Notebook Actions",
            border_style="border",
            style="main",
            padding=(2, 4),
        )

    if state.current_view == View.NOTEBOOK_LIST:
        if not state.selected_notebook:
            return Panel(
                Align.center("No notebook selected.", vertical="middle"),
                title="Notebook Details",
                border_style="border",
                style="main",
            )

        # Trigger background fetch for summary if not cached
        fetch_summary_if_needed(state)

        # Find selected notebook
        nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
        if not nb:
            return Panel(
                Align.center("Notebook not found.", vertical="middle"),
                title="Notebook Details",
                border_style="border",
                style="main",
            )

        title = getattr(nb, "title", "Unknown Notebook")
        sources = str(getattr(nb, "sources_count", 0))
        summary_text = state.notebook_summaries.get(state.selected_notebook, "Loading summary...")

        # Format the content
        title_text = Text(title, style="bold accent", justify="center")
        sources_text = Text(f"{sources} Sources", style="info", justify="center")
        summary_display = Text(f"\n\n{summary_text}", style="foreground")

        content = Group(Align.center(title_text), Align.center(sources_text), summary_display)

        return Panel(
            content, title="Notebook Details", border_style="border", style="main", padding=(1, 2)
        )

    placeholder_content = f"Placeholder for {state.current_view.name}"
    return Panel(
        Align.center(placeholder_content, vertical="middle"),
        title=state.current_view.name.replace("_", " ").title(),
        border_style="border",
        style="main",
    )
