from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from notebooklm._app.tracing import trace_url

from ..jobs.store import ItemStatus, Job, JobStatus
from ..state import TUIState
from ._widgets import empty_panel, key_hints, panel

_JOB_KEYS = [
    ("x", "cancel"),
    ("R", "retry"),
    ("C", "clear finished"),
    ("f", "filter"),
    ("j/k", "move"),
]

_ITEM_GLYPHS = {
    ItemStatus.PENDING: ("○", "muted"),
    ItemStatus.RUNNING: ("◐", "info"),
    ItemStatus.DONE: ("✓", "success"),
    ItemStatus.FAILED: ("✗", "error"),
    ItemStatus.SKIPPED: ("–", "muted"),
}

_STATUS_STYLE = {
    JobStatus.QUEUED: "muted",
    JobStatus.RUNNING: "info",
    JobStatus.DONE: "success",
    JobStatus.FAILED: "error",
    JobStatus.CANCELLED: "warning",
    JobStatus.INTERRUPTED: "warning",
}


def visible_jobs(state: TUIState) -> list[Job]:
    """Cached job list filtered by ``jobs_view`` kind and status."""
    kind = state.jobs_view.get("kind")
    status = state.jobs_view.get("status")
    return [
        j
        for j in state.jobs_snapshot
        if (kind is None or j.kind == kind) and (status is None or j.status == status)
    ]


def cursor_index(state: TUIState, count: int) -> int:
    """Jobs cursor clamped to the visible list."""
    return min(max(state.jobs_view.get("cursor", 0), 0), max(count - 1, 0))


def selected_job(state: TUIState) -> Job | None:
    jobs = visible_jobs(state)
    if not jobs:
        return None
    return jobs[cursor_index(state, len(jobs))]


def _percent_bar(percent: float, width: int = 10) -> Text:
    filled = round(min(max(percent, 0.0), 100.0) / 100 * width)
    text = Text(no_wrap=True)
    text.append("█" * filled, style="success")
    text.append("░" * (width - filled), style="subtle")
    text.append(f" {percent:3.0f}%", style="muted")
    return text


def _list_panel(state: TUIState) -> Panel:
    jobs = visible_jobs(state)
    status = state.jobs_view.get("status")
    title = f"Jobs · filter {status.value if status else 'all'}"
    if not jobs:
        return empty_panel(title)

    cursor = cursor_index(state, len(jobs))
    table = Table.grid(expand=True, padding=(0, 1))
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True)
    table.add_column(no_wrap=True, overflow="ellipsis", ratio=1)
    for idx, job in enumerate(jobs):
        row_style = "selected" if idx == cursor else ""
        table.add_row(
            Text(job.kind, style=row_style),
            Text(job.notebook_id or "-", style=row_style or "muted"),
            Text(job.status.value, style=_STATUS_STYLE.get(job.status, "muted")),
            _percent_bar(job.percent),
            Text(job.phase, style=row_style or "muted"),
        )
    return panel(table, title)


def _item_lines(state: TUIState, job: Job) -> list[Text]:
    if state.job_store is None:
        return []
    lines: list[Text] = []
    for item in state.job_store.items(job.id):
        glyph, style = _ITEM_GLYPHS[item.status]
        line = Text(no_wrap=True, overflow="ellipsis")
        line.append(f"{glyph} ", style=style)
        line.append(item.name)
        lines.append(line)
        if item.error:
            lines.append(Text(f"    {item.error}", style="error"))
    return lines


def _detail_panel(state: TUIState) -> Panel:
    job = selected_job(state)
    if job is None:
        return panel(Text("No jobs match the filter.", style="muted"), "Job")

    lines: list[Text | Group] = [
        Text(f"{job.kind}  {job.id}", style="heading"),
        Text(f"status {job.status.value}", style=_STATUS_STYLE.get(job.status, "muted")),
        Text(f"phase  {job.phase or '-'}", style="foreground"),
    ]
    if job.error:
        lines.append(Text(f"error  {job.error}", style="error"))
    if job.summary:
        lines.append(Text(f"result {job.summary}", style="success"))
    items = _item_lines(state, job)
    if items:
        lines.append(Text(""))
        lines.extend(items)
    url = trace_url(job.trace_id)
    if url:
        lines.append(Text(""))
        lines.append(Text(f"trace  {url}", style="info"))
    lines.append(Text(""))
    lines.append(key_hints(_JOB_KEYS))
    return panel(Group(*lines), "Job")


def render_jobs(state: TUIState) -> tuple[Panel, Panel]:
    """Return ``(list_panel, detail_panel)`` for Jobs mode."""
    return _list_panel(state), _detail_panel(state)
