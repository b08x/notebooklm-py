from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState, View
from ..views.notebook_detail import fetch_summary_if_needed
from .chat import render_chat
from .compiler import render_compiler
from .logs import render_logs


def _render_ingest_progress(progress: dict) -> Text:
    total = progress.get("total_sources", 0)
    done = progress.get("done_sources", 0)
    title = progress.get("current_title", "")
    chunks_done = progress.get("current_chunks_done", 0)
    chunks_total = progress.get("current_chunks_total", 0)
    failures = progress.get("failures", [])

    body = Text()
    body.append(f"\nSources: {done}/{total}\n", style="info")
    if title:
        chunk_part = f" ({chunks_done}/{chunks_total} chunks embedded)" if chunks_total else ""
        body.append(f"Current: {title}{chunk_part}\n", style="foreground")
    if failures:
        body.append(f"\n{len(failures)} failed so far:\n", style="warning")
        for failed_title, error in failures[-5:]:
            body.append(f"  · {failed_title}: {error}\n", style="error")
        body.append("See the Logs view (L) for full tracebacks.\n", style="muted")
    return body


def render_main(state: TUIState) -> tuple[Panel, Panel]:
    if state.editing_context:
        buffer_text = Text(f"{state.context_edit_buffer}█", style="foreground")
        edit_panel = Panel(
            buffer_text,
            title="Customize Embedding Context — Enter to save, Esc to cancel",
            border_style="border",
            style="main",
            padding=(1, 2),
        )
        hint = Panel(
            Align.center(
                "This text is prepended to each chunk before embedding (contextual "
                "retrieval). Cleared text disables the context prefix for this "
                "notebook's ingestion/assessment runs.",
                vertical="middle",
            ),
            title="Details",
            border_style="border",
        )
        return edit_panel, hint

    if state.selecting_sources:
        rows = Text()
        if not state.ingest_sources:
            rows.append("No sources found for this notebook.", style="muted")
        else:
            for i, src in enumerate(state.ingest_sources):
                checked = "x" if src.id in state.ingest_selected else " "
                src_title = getattr(src, "title", None) or src.id
                cursor = "▶ " if i == state.ingest_cursor else "  "
                style = "selected" if i == state.ingest_cursor else "foreground"
                rows.append(f"{cursor}[{checked}] {src_title}\n", style=style)

        picker_panel = Panel(
            rows,
            title=(
                f"Select Sources to Ingest "
                f"({len(state.ingest_selected)}/{len(state.ingest_sources)} selected)"
            ),
            border_style="border",
            style="main",
            padding=(1, 2),
        )
        hint = Panel(
            Align.center(
                "[space] toggle  ·  [a] all  ·  [n] none  ·  [j/k] move  ·  "
                "[Enter] start ingest  ·  [Esc] cancel",
                vertical="middle",
            ),
            title="Details",
            border_style="border",
        )
        return picker_panel, hint

    if state.current_view == View.CHAT:
        return render_chat(state)
    elif state.current_view == View.COMPILER:
        return render_compiler(state)
    elif state.current_view == View.ASSESSMENT:
        from ..views.assessment_view import AssessmentView

        return AssessmentView(state).render()
    elif state.current_view == View.LOGS:
        return render_logs(state)

    if state.current_view == View.NOTEBOOK_DETAIL:
        if not state.selected_notebook:
            empty_panel = Panel(
                Align.center("No notebook selected.", vertical="middle"),
                title="Notebook Actions",
                border_style="border",
                style="main",
            )
            return empty_panel, Panel("", border_style="border")

        nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
        title = getattr(nb, "title", "Unknown Notebook") if nb else "Unknown Notebook"

        menu_items = [
            "1. Chat with Notebook",
            "2. Download Assets (Sources, Overviews)",
            "3. Ingest Sources into Database (Pipeline)",
            "4. Assess Audio Overview",
        ]
        has_override = state.selected_notebook in state.context_overrides
        context_hint = (
            "[e] customize embedding context"
            f"{' (customized)' if has_override else ' (using notebook summary)'}"
        )

        # Render the menu
        menu_text = Text()
        for i, item in enumerate(menu_items):
            if i == state.detail_menu_index:
                menu_text.append(f"▶ {item}\n", style="selected")
            else:
                menu_text.append(f"  {item}\n", style="foreground")

        title_text = Text(title, style="bold primary", justify="center")

        actions_panel = Panel(
            Group(
                Align.center(title_text),
                Text("\nWhat would you like to do?\n", justify="center", style="info"),
                Align.center(menu_text),
                Text(f"\n{context_hint}", justify="center", style="muted"),
            ),
            title="Notebook Actions",
            border_style="border",
            style="main",
            padding=(2, 4),
        )

        return actions_panel, Panel(
            Align.center("Select an action to proceed.", vertical="middle"),
            title="Details",
            border_style="border",
        )

    if state.current_view == View.NOTEBOOK_LIST:
        if not state.selected_notebook:
            empty_panel = Panel(
                Align.center("No notebook selected.", vertical="middle"),
                title="Notebook List",
                border_style="border",
                style="main",
            )
            return empty_panel, Panel("", border_style="border")

        # Trigger background fetch for summary if not cached
        fetch_summary_if_needed(state)

        # Find selected notebook
        nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
        if not nb:
            not_found = Panel(
                Align.center("Notebook not found.", vertical="middle"),
                title="Notebook Details",
                border_style="border",
                style="main",
            )
            return not_found, Panel("", border_style="border")

        title = getattr(nb, "title", "Unknown Notebook")
        sources = str(getattr(nb, "sources_count", 0))
        summary_text = state.notebook_summaries.get(state.selected_notebook, "Loading summary...")

        title_text = Text(title, style="bold accent", justify="center")
        sources_text = Text(f"{sources} Sources", style="info", justify="center")

        # We put the list/actions in results and summary in detail
        results_panel = Panel(
            Group(
                Align.center(title_text),
                Align.center(sources_text),
                Text("\n[Enter] to view details.", justify="center", style="muted"),
            ),
            title="Notebook Info",
            border_style="border",
            style="main",
            padding=(1, 2),
        )

        ingest_active = bool(
            state.background_task
            and not state.background_task.done()
            and state.ingest_progress.get("total_sources") is not None
        )
        if ingest_active:
            detail_panel = Panel(
                _render_ingest_progress(state.ingest_progress),
                title="Ingesting",
                border_style="border",
                style="main",
                padding=(1, 2),
            )
        else:
            detail_panel = Panel(
                Text(f"\n{summary_text}", style="foreground"),
                title="Summary",
                border_style="border",
                style="main",
                padding=(1, 2),
            )

        return results_panel, detail_panel

    placeholder_content = f"Placeholder for {state.current_view.name}"
    return (
        Panel(
            Align.center(placeholder_content, vertical="middle"),
            title=state.current_view.name.replace("_", " ").title() + " Results",
            border_style="border",
            style="main",
        ),
        Panel(
            Align.center("Detail pane", vertical="middle"),
            title="Details",
            border_style="border",
            style="main",
        ),
    )
