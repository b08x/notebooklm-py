import datetime
from collections import Counter
from typing import Any

from rich.console import Group
from rich.panel import Panel
from rich.progress_bar import ProgressBar
from rich.table import Table
from rich.text import Text

from ..state import TUIState, View
from ._widgets import empty_panel, hint_panel, key_hints, message_panel, panel
from .chat import render_chat
from .compiler import render_compiler
from .logs import render_logs
from .sidebar import styled_title


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
    body.append("Sources  ", style="label")
    body.append(f"{done}/{total}\n", style="foreground")
    if title:
        body.append("Current  ", style="label")
        body.append(title, style="foreground")
        if chunks_total:
            body.append(f"  {chunks_done}/{chunks_total} chunks embedded", style="muted")
        body.append("\n")
    if failures:
        body.append(f"\n{len(failures)} failed so far\n", style="warning")
        for failed_title, error in failures[-5:]:
            body.append(f"  ✗ {failed_title}: {error}\n", style="error")
        body.append("\n")
        body.append_text(key_hints([("L", "full tracebacks in Logs")]))
    return body


def _get_stats(state: TUIState, nb_id: str) -> dict | None:
    stats = state.notebook_stats.get(nb_id)
    cache = getattr(state, "tui_cache", None)
    if not stats and cache is not None:
        stats = cache.get_artifact_stats(nb_id)
    return stats


def _stats_table(stats: dict, include_sources: bool = False) -> Table:
    """Key/value table for artifact stats: muted labels, plain values."""
    table = Table.grid(padding=(0, 2))
    table.add_column("Key", style="label", justify="right", no_wrap=True)
    table.add_column("Value", style="foreground")

    if include_sources and stats.get("source_count") is not None:
        table.add_row("Sources", str(stats.get("source_count", 0)))
    art_count = (
        stats.get("total_artifacts")
        if stats.get("total_artifacts") is not None
        else stats.get("artifact_count", 0)
    )
    table.add_row("Artifacts", str(art_count))

    counts = stats.get("counts")
    if not (counts and isinstance(counts, dict)):
        counts = Counter(stats.get("artifact_types", []))
    if counts:
        types_str = ", ".join(f"{k.replace('_', ' ').title()} ({v})" for k, v in counts.items())
        table.add_row("Types", types_str)

    audio_ts = None
    for art in stats.get("artifacts", []):
        if art.get("kind", "") in ("audio", "audio_overview") and art.get("timestamp"):
            if audio_ts is None or art["timestamp"] > audio_ts:
                audio_ts = art["timestamp"]

    if stats.get("has_audio", False):
        audio = Text("● Ready", style="success")
        if audio_ts:
            audio.append(f"  {format_relative_time(audio_ts)}", style="muted")
    else:
        audio = Text("None", style="muted")
    table.add_row("Audio Overview", audio)

    recent_ts = stats.get("recent_generated_at")
    if recent_ts:
        table.add_row("Last Generated", format_relative_time(recent_ts))
    return table


def _stats_block(stats: dict | None, include_sources: bool = False) -> list[Any]:
    if not stats:
        return []
    if stats.get("loading"):
        return [Text("Loading statistics…", style="muted")]
    if "error" in stats:
        return [Text(f"Failed to load stats: {stats['error']}", style="error")]
    return [_stats_table(stats, include_sources)]


def _cursor_list(items: list[str], cursor: int) -> Table:
    rows = Table.grid(expand=True)
    rows.add_column(width=2, no_wrap=True)
    rows.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    for i, item in enumerate(items):
        is_selected = i == cursor
        rows.add_row(
            Text("▌" if is_selected else " ", style="marker"),
            Text(item),
            style="selected" if is_selected else "foreground",
        )
    return rows


def _render_artifact_selection(state: TUIState) -> tuple[Panel, Panel]:
    if not state.audio_artifacts:
        body: Any = Text("No audio artifacts found for this notebook.", style="muted")
    else:
        titles = [getattr(a, "title", None) or a.id for a in state.audio_artifacts]
        body = _cursor_list(titles, state.artifact_cursor)

    picker_panel = panel(body, "Select Audio Overview", focused=True, padding=(1, 2))
    hint = hint_panel([("j/k", "move"), ("enter", "start assessment"), ("esc", "cancel")])
    return picker_panel, hint


def _render_notebook_detail(state: TUIState, nb_id: str) -> tuple[Panel, Panel]:
    # Fetch stats and summary in background if needed
    from ..views.notebook_detail import fetch_stats_if_needed, fetch_summary_if_needed

    fetch_stats_if_needed(state)
    fetch_summary_if_needed(state)

    nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
    title = getattr(nb, "title", "Unknown Notebook") if nb else "Unknown Notebook"

    menu_items = [
        "Chat with notebook",
        "Download assets",
        "Ingest sources into database",
        "Assess audio overview",
        "Assess visual artifacts",
    ]
    numbered = [f"{i}  {item}" for i, item in enumerate(menu_items, start=1)]
    has_override = state.selected_notebook in state.context_overrides
    context_state = "customized" if has_override else "using notebook summary"

    actions_panel = panel(
        Group(
            styled_title(title, style="heading"),
            Text(""),
            _cursor_list(numbered, state.detail_menu_index),
            Text(""),
            key_hints([("enter", "run"), ("e", f"embedding context ({context_state})")]),
        ),
        "Actions",
        focused=True,
        padding=(1, 2),
    )

    detail_group: list[Any] = []
    summary_text = state.notebook_summaries.get(nb_id, "Loading summary…")
    detail_group.append(Text("Summary", style="heading"))
    detail_group.append(Text(summary_text, style="foreground"))

    stats_items = _stats_block(_get_stats(state, nb_id), include_sources=True)
    if stats_items:
        detail_group.append(Text(""))
        detail_group.append(Text("Statistics", style="heading"))
        detail_group.extend(stats_items)

    downloading = bool(
        state.background_task and not state.background_task.done() and state.download_progress
    )
    if downloading or state.download_progress.get("done"):
        prog = state.download_progress
        detail_group.append(Text(""))
        detail_group.append(Text("Download", style="heading"))
        status = Text(prog.get("phase", "…"), style="info")
        if prog.get("done"):
            status = Text("✓ complete", style="success")
        detail_group.append(status)
        detail_group.append(
            ProgressBar(
                total=1.0,
                completed=prog.get("percent", 0.0),
                width=40,
                complete_style="primary",
                finished_style="success",
                style="subtle",
            )
        )

    return actions_panel, panel(Group(*detail_group), "Details", padding=(1, 2))


def _render_notebook_info(state: TUIState, nb_id: str) -> tuple[Panel, Panel]:
    nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
    if not nb:
        return message_panel("Notebook not found.", "Notebook"), empty_panel("Summary")

    title = getattr(nb, "title", "Unknown Notebook")
    sources = str(getattr(nb, "sources_count", 0))
    summary_text = state.notebook_summaries.get(
        nb_id, "Press Enter to load the notebook summary and details."
    )

    info_items: list[Any] = [
        styled_title(title, style="heading"),
        Text(f"{sources} Sources", style="muted"),
    ]
    stats_items = _stats_block(_get_stats(state, nb_id))
    if stats_items:
        info_items.append(Text(""))
        info_items.extend(stats_items)
    info_items.append(Text(""))
    info_items.append(key_hints([("enter", "open notebook")]))

    results_panel = panel(Group(*info_items), "Notebook", padding=(1, 2))

    ingest_active = bool(
        state.background_task
        and not state.background_task.done()
        and state.ingest_progress.get("total_sources") is not None
    )
    if ingest_active:
        detail_panel = panel(
            _render_ingest_progress(state.ingest_progress), "Ingesting", padding=(1, 2)
        )
    else:
        detail_panel = panel(Text(summary_text, style="foreground"), "Summary", padding=(1, 2))

    return results_panel, detail_panel


def render_main(state: TUIState) -> tuple[Panel, Panel]:
    if state.selecting_artifact:
        return _render_artifact_selection(state)

    if state.editing_context:
        buffer_text = Text(state.context_edit_buffer, style="foreground")
        buffer_text.append("▏", style="prompt")
        edit_panel = panel(buffer_text, "Embedding Context", focused=True, padding=(1, 2))
        hint = panel(
            Group(
                Text(
                    "This text is prepended to each chunk before embedding (contextual "
                    "retrieval). Clearing it disables the context prefix for this "
                    "notebook's ingestion and assessment runs.",
                    style="muted",
                ),
                Text(""),
                key_hints([("enter", "save"), ("esc", "cancel")]),
            ),
            "Details",
            padding=(1, 2),
        )
        return edit_panel, hint

    if state.selecting_sources:
        if not state.ingest_sources:
            body: Any = Text("No sources found for this notebook.", style="muted")
        else:
            items = []
            for src in state.ingest_sources:
                checked = "■" if src.id in state.ingest_selected else "□"
                src_title = getattr(src, "title", None) or src.id
                if src.id in getattr(state, "ingest_completed", set()):
                    src_title += "  (already ingested)"
                items.append(f"{checked} {src_title}")
            body = _cursor_list(items, state.ingest_cursor)

        picker_panel = panel(
            body,
            f"Select Sources  {len(state.ingest_selected)}/{len(state.ingest_sources)}",
            focused=True,
            padding=(1, 2),
        )
        hint = hint_panel(
            [
                ("space", "toggle"),
                ("a", "all"),
                ("n", "none"),
                ("j/k", "move"),
                ("enter", "ingest"),
                ("esc", "cancel"),
            ]
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

    if state.current_view in (View.NOTEBOOK_DETAIL, View.NOTEBOOK_LIST):
        if not state.selected_notebook:
            return message_panel("No notebook selected.", "Notebook"), empty_panel("Details")
        if state.current_view == View.NOTEBOOK_DETAIL:
            return _render_notebook_detail(state, state.selected_notebook)
        return _render_notebook_info(state, state.selected_notebook)

    view_title = state.current_view.name.replace("_", " ").title()
    return (
        message_panel(f"Placeholder for {state.current_view.name}", view_title),
        message_panel("Detail pane", "Details"),
    )
