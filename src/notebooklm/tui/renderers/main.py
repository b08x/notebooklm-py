import datetime
from typing import Any

from rich.align import Align
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState, View
from .chat import render_chat
from .compiler import render_compiler
from .logs import render_logs


def format_relative_time(
    ts: float | int | datetime.datetime | None,
    now: float | int | datetime.datetime | None = None,
) -> str:
    """Format a timestamp into a concise, human-readable relative time string.

    Examples: 'just now', '2m ago', '3h ago', 'Yesterday', 'Sep 15'.
    """
    if ts is None:
        return ""
    if isinstance(ts, (int, float)):
        try:
            dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        except Exception:
            return ""
    elif isinstance(ts, datetime.datetime):
        dt = ts if ts.tzinfo is not None else ts.replace(tzinfo=datetime.timezone.utc)
    else:
        return ""

    if now is None:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
    elif isinstance(now, (int, float)):
        try:
            now_dt = datetime.datetime.fromtimestamp(now, tz=datetime.timezone.utc)
        except Exception:
            now_dt = datetime.datetime.now(datetime.timezone.utc)
    elif isinstance(now, datetime.datetime):
        now_dt = now if now.tzinfo is not None else now.replace(tzinfo=datetime.timezone.utc)
    else:
        now_dt = datetime.datetime.now(datetime.timezone.utc)

    diff = (now_dt - dt).total_seconds()
    if diff < 0:
        return "just now"
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{int(diff // 60)}m ago"
    if diff < 86400:
        return f"{int(diff // 3600)}h ago"
    if diff < 172800:
        return "Yesterday"

    day_str = str(dt.day)
    month_str = dt.strftime("%b")
    if dt.year == now_dt.year:
        return f"{month_str} {day_str}"
    return f"{month_str} {day_str}, {dt.year}"


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


def _render_artifact_selection(state: TUIState) -> tuple[Panel, Panel]:
    rows = Text()
    if not state.audio_artifacts:
        rows.append("No audio artifacts found for this notebook.", style="muted")
    else:
        for i, artifact in enumerate(state.audio_artifacts):
            artifact_title = getattr(artifact, "title", None) or artifact.id
            cursor = "▶ " if i == state.artifact_cursor else "  "
            style = "selected" if i == state.artifact_cursor else "foreground"
            rows.append(f"{cursor}{artifact_title}\n", style=style)

    picker_panel = Panel(
        rows,
        title="Select Audio Overview to Assess",
        border_style="border",
        style="main",
        padding=(1, 2),
    )
    hint = Panel(
        Align.center(
            "[j/k] move  ·  [Enter] start assessment  ·  [Esc] cancel",
            vertical="middle",
        ),
        title="Details",
        border_style="border",
    )
    return picker_panel, hint


def render_main(state: TUIState) -> tuple[Panel, Panel]:
    if state.selecting_artifact:
        return _render_artifact_selection(state)

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
                if src.id in getattr(state, "ingest_completed", set()):
                    src_title += " (already ingested)"
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
    elif state.current_view == View.VISUAL_ASSESSMENT:
        from ..views.visual_assessment_view import VisualAssessmentView

        return VisualAssessmentView(state).render()
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

        # Fetch stats and summary in background if needed
        from ..views.notebook_detail import fetch_stats_if_needed, fetch_summary_if_needed

        fetch_stats_if_needed(state)
        fetch_summary_if_needed(state)

        nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
        title = getattr(nb, "title", "Unknown Notebook") if nb else "Unknown Notebook"

        menu_items = [
            "1. Chat with Notebook",
            "2. Download Assets (Sources, Overviews)",
            "3. Ingest Sources into Database (Pipeline)",
            "4. Assess Audio Overview",
            "5. Assess Visual Artifacts",
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

        title_text = Text(title, style="bold_primary", justify="center")

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

        # Build details panel
        detail_group: list[Any] = []

        # 1. Summary
        summary_text = state.notebook_summaries.get(state.selected_notebook, "Loading summary...")
        detail_group.append(Text("\nNotebook Summary", style="bold_accent", justify="center"))
        detail_group.append(Text(f"{summary_text}\n", style="foreground"))

        # 2. Stats
        stats = state.notebook_stats.get(state.selected_notebook)
        cache = getattr(state, "tui_cache", None)
        if not stats and cache is not None:
            stats = cache.get_artifact_stats(state.selected_notebook)

        if stats:
            if stats.get("loading"):
                detail_group.append(
                    Text("\nLoading statistics...", style="muted", justify="center")
                )
            elif "error" in stats:
                detail_group.append(
                    Text(
                        f"\nFailed to load stats: {stats['error']}", style="error", justify="center"
                    )
                )
            else:
                from rich.table import Table

                table = Table(show_header=False, box=None, padding=(0, 2))
                table.add_column("Key", style="bold_info", justify="right")
                table.add_column("Value", style="foreground")

                if stats.get("source_count") is not None:
                    table.add_row("Sources", str(stats.get("source_count", 0)))
                art_count = (
                    stats.get("total_artifacts")
                    if stats.get("total_artifacts") is not None
                    else stats.get("artifact_count", 0)
                )
                table.add_row("Artifacts", str(art_count))

                counts = stats.get("counts")
                if counts and isinstance(counts, dict):
                    types_str = ", ".join(
                        f"{k.replace('_', ' ').title()} ({v})" for k, v in counts.items()
                    )
                    table.add_row("Artifact Types", types_str)
                else:
                    types = stats.get("artifact_types", [])
                    if types:
                        from collections import Counter

                        counts_c = Counter(types)
                        types_str = ", ".join(
                            f"{k.replace('_', ' ').title()} ({v})" for k, v in counts_c.items()
                        )
                        table.add_row("Artifact Types", types_str)

                # Audio Overview status & relative timestamp
                has_audio = stats.get("has_audio", False)
                audio_ts = None
                for art in stats.get("artifacts", []):
                    kind = art.get("kind", "")
                    if kind in ("audio", "audio_overview") and art.get("timestamp"):
                        if audio_ts is None or art["timestamp"] > audio_ts:
                            audio_ts = art["timestamp"]

                if has_audio:
                    if audio_ts:
                        rel_audio = format_relative_time(audio_ts)
                        table.add_row("Audio Overview", f"Ready (generated {rel_audio})")
                    else:
                        table.add_row("Audio Overview", "Ready")
                else:
                    table.add_row("Audio Overview", "None")

                recent_ts = stats.get("recent_generated_at")
                if recent_ts:
                    table.add_row("Last Generated", format_relative_time(recent_ts))

                detail_group.append(
                    Text("\nNotebook Statistics", style="bold_accent", justify="center")
                )
                detail_group.append(Text(""))
                detail_group.append(Align.center(table))

        # Check if download is running
        downloading = bool(
            state.background_task and not state.background_task.done() and state.download_progress
        )
        if downloading or state.download_progress.get("done"):
            from rich.progress_bar import ProgressBar

            prog = state.download_progress
            phase = prog.get("phase", "...")
            percent = prog.get("percent", 0.0)

            detail_group.append(
                Text("\n\n[Download Status]", style="bold_primary", justify="center")
            )
            detail_group.append(Text(f"{phase}", style="info", justify="center"))
            bar = ProgressBar(total=1.0, completed=percent, width=50)
            detail_group.append(Align.center(bar))

            if prog.get("done"):
                detail_group.append(Text("\n(Download Complete)", style="muted", justify="center"))

        if not detail_group:
            detail_group.append(Align.center("Select an action to proceed.", vertical="middle"))

        return actions_panel, Panel(
            Group(*detail_group), title="Details", border_style="border", style="main"
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
        summary_text = state.notebook_summaries.get(
            state.selected_notebook, "Press [Enter] to load notebook summary and details."
        )

        title_text = Text(title, style="bold_accent", justify="center")
        sources_text = Text(f"{sources} Sources", style="info", justify="center")

        stats = state.notebook_stats.get(state.selected_notebook)
        cache = getattr(state, "tui_cache", None)
        if not stats and cache is not None:
            stats = cache.get_artifact_stats(state.selected_notebook)

        info_items: list[Any] = [
            Align.center(title_text),
            Align.center(sources_text),
        ]

        if stats and not stats.get("loading") and "error" not in stats:
            from rich.table import Table

            table = Table(show_header=False, box=None, padding=(0, 2))
            table.add_column("Key", style="bold_info", justify="right")
            table.add_column("Value", style="foreground")

            art_count = (
                stats.get("total_artifacts")
                if stats.get("total_artifacts") is not None
                else stats.get("artifact_count", 0)
            )
            table.add_row("Artifacts", str(art_count))

            counts = stats.get("counts")
            if counts and isinstance(counts, dict):
                types_str = ", ".join(
                    f"{k.replace('_', ' ').title()} ({v})" for k, v in counts.items()
                )
                table.add_row("Artifact Types", types_str)
            else:
                types = stats.get("artifact_types", [])
                if types:
                    from collections import Counter

                    c = Counter(types)
                    types_str = ", ".join(
                        f"{k.replace('_', ' ').title()} ({v})" for k, v in c.items()
                    )
                    table.add_row("Artifact Types", types_str)

            has_audio = stats.get("has_audio", False)
            audio_ts = None
            for art in stats.get("artifacts", []):
                kind = art.get("kind", "")
                if kind in ("audio", "audio_overview") and art.get("timestamp"):
                    if audio_ts is None or art["timestamp"] > audio_ts:
                        audio_ts = art["timestamp"]

            if has_audio:
                if audio_ts:
                    rel_audio = format_relative_time(audio_ts)
                    table.add_row("Audio Overview", f"Ready (generated {rel_audio})")
                else:
                    table.add_row("Audio Overview", "Ready")
            else:
                table.add_row("Audio Overview", "None")

            recent_ts = stats.get("recent_generated_at")
            if recent_ts:
                table.add_row("Last Generated", format_relative_time(recent_ts))

            info_items.append(Text(""))
            info_items.append(Align.center(table))
        elif stats and stats.get("loading"):
            info_items.append(Text("\nLoading statistics...", style="muted", justify="center"))
        elif stats and "error" in stats:
            info_items.append(
                Text(f"\nFailed to load stats: {stats['error']}", style="error", justify="center")
            )

        info_items.append(Text("\n[Enter] to view details.", justify="center", style="muted"))

        # We put the list/actions in results and summary in detail
        results_panel = Panel(
            Group(*info_items),
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
