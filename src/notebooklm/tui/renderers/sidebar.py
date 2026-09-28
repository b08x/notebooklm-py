import datetime
import re

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.panel import Panel
from rich.segment import Segment
from rich.table import Table
from rich.text import Text

from ..state import SORT_LABELS, TUIState, View
from ._widgets import key_hints, panel

# Single-cell glyphs. Emoji with a variation selector (🎙️, ⚙️) are measured as
# one cell by Rich but drawn as two by most terminals, which shifts every
# following column and corrupts the Live frame.
BADGE_AUDIO = "♪"
BADGE_DOCS = "≡"
BADGE_RECENT = "✦"
_BADGE_STYLES = {
    BADGE_AUDIO: "badge.audio",
    BADGE_DOCS: "badge.docs",
    BADGE_RECENT: "badge.recent",
}

# Lines inside the panel that are not notebook rows: list heading, blank line,
# blank line + two lines of list keys.
_CHROME_LINES = 5


def _tag_style(raw_tag: str) -> str:
    if "GEMINI" in raw_tag:
        return "tag.gemini"
    if "CLAUDE" in raw_tag:
        return "tag.claude"
    if "SFL" in raw_tag or "ENG" in raw_tag:
        return "tag.eng"
    if "TEST" in raw_tag or "DEV" in raw_tag:
        return "tag.dev"
    return "tag.other"


def _parse_domain_tag(title: str) -> tuple[str, str, str]:
    """Extract [DOMAIN] tag, assign a color style, and return (rendered_chip, clean_title, raw_tag)."""
    match = re.match(r"^\[([A-Za-z0-9_-]+)\]\s*(.*)$", title)
    if not match:
        return "", title, ""

    raw_tag = match.group(1).upper()
    clean_title = match.group(2)
    style = _tag_style(raw_tag)
    chip = f"[{style}]\\[{raw_tag}][/{style}] "
    return chip, clean_title, raw_tag


def _get_artifact_badges(nb_id: str, state: TUIState) -> str:
    """Return compact badges for audio, documents/notes, and recent activity."""
    stats = state.notebook_stats.get(nb_id)
    cache = getattr(state, "tui_cache", None)
    if not stats and cache is not None:
        stats = cache.get_artifact_stats(nb_id)

    if not stats:
        return ""

    badges = []
    if stats.get("has_audio"):
        badges.append(BADGE_AUDIO)
    if stats.get("has_notes") or stats.get("total_artifacts", 0) > 0:
        badges.append(BADGE_DOCS)

    # Recent activity indicator (generated within last 48 hours)
    recent_ts = stats.get("recent_generated_at")
    if recent_ts:
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if (now_ts - recent_ts) < 172800:  # 48 hours
            badges.append(BADGE_RECENT)

    return "".join(badges)


def styled_title(raw_title: str, style: str = "") -> Text:
    """Notebook title with its [DOMAIN] prefix shown as a colored lowercase tag."""
    _, clean_title, raw_tag = _parse_domain_tag(raw_title)
    title = Text(no_wrap=True, overflow="ellipsis", style=style)
    if raw_tag:
        title.append(raw_tag.lower(), style=_tag_style(raw_tag))
        title.append(" ")
    title.append(clean_title)
    return title


def _badge_text(badges: str) -> Text:
    text = Text(no_wrap=True)
    for glyph in badges:
        text.append(glyph, style=_BADGE_STYLES.get(glyph, "muted"))
    return text


def _list_heading(state: TUIState) -> Text:
    heading = Text(no_wrap=True, overflow="ellipsis")
    heading.append(SORT_LABELS.get(state.sort_key, state.sort_key), style="label")
    if state.search_query or state.searching:
        typing = "…" if state.searching else ""
        heading.append("  / ", style="key")
        heading.append(f"{state.search_query}{typing}", style="foreground")
    return heading


def _toggle(text: Text, key: str, label: str, on: bool) -> None:
    text.append(key, style="key")
    text.append(f" {label}", style="success" if on else "muted")
    text.append(" ✓" if on else "", style="success")


def _list_keys(state: TUIState) -> Group:
    toggles = Text(no_wrap=True, overflow="ellipsis")
    _toggle(toggles, "o", "audio", state.filter_has_audio)
    toggles.append("  ")
    _toggle(toggles, "z", "non-empty", state.filter_min_sources)
    return Group(
        key_hints([("/", "search"), ("s", "sort"), ("r", "refresh")], sep="  "),
        toggles,
    )


class _NotebookList:
    """Notebook rows sized to the space the Layout actually gives the sidebar."""

    def __init__(self, state: TUIState) -> None:
        self.state = state

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        state = self.state
        notebooks = state.get_filtered_and_sorted_notebooks()
        visible_rows = max(1, (options.height or 20) - _CHROME_LINES)
        state.sidebar_rows = visible_rows

        current_id = state.selected_notebook
        try:
            current_idx = next(i for i, nb in enumerate(notebooks) if nb.id == current_id)
        except StopIteration:
            current_idx = 0
            if notebooks and not state.selected_notebook:
                state.selected_notebook = notebooks[0].id

        if current_idx < state.scroll_offset:
            state.scroll_offset = current_idx
        elif current_idx >= state.scroll_offset + visible_rows:
            state.scroll_offset = current_idx - visible_rows + 1
        state.scroll_offset = max(
            0, min(state.scroll_offset, max(0, len(notebooks) - visible_rows))
        )

        rows = Table.grid(expand=True)
        rows.add_column(width=2, no_wrap=True)
        rows.add_column(ratio=1, no_wrap=True, overflow="ellipsis")
        rows.add_column(no_wrap=True)
        rows.add_column(justify="right", no_wrap=True, min_width=3)

        for nb in notebooks[state.scroll_offset : state.scroll_offset + visible_rows]:
            raw_title = getattr(nb, "title", "Unknown") or "Unknown"
            is_selected = nb.id == state.selected_notebook
            sources_cnt = getattr(nb, "sources_count", 0)
            try:
                sources_str = str(int(sources_cnt) if sources_cnt is not None else 0)
            except (ValueError, TypeError):
                sources_str = str(sources_cnt)

            title = styled_title(raw_title)

            badges = _badge_text(_get_artifact_badges(nb.id, state))
            if badges.plain:
                badges = Text(" ") + badges
            rows.add_row(
                Text("▌" if is_selected else " ", style="marker"),
                title,
                badges,
                Text(sources_str, style="muted"),
                style="selected" if is_selected else "foreground",
            )

        heading = _list_heading(state)
        if not notebooks:
            filtered = state.search_query or state.filter_has_audio or state.filter_min_sources
            empty = "No matching notebooks." if filtered else "No notebooks found."
            body: Group = Group(heading, Text(""), Text(empty, style="muted"))
        else:
            body = Group(heading, Text(""), rows)

        lines = console.render_lines(body, options.update(height=None), pad=False)
        keys = console.render_lines(
            Group(Text(""), _list_keys(state)), options.update(height=None), pad=False
        )
        height = options.height or (len(lines) + len(keys))
        lines = lines[: max(0, height - len(keys))]
        filler = max(0, height - len(lines) - len(keys))
        yield from _emit(lines)
        yield from _emit([[] for _ in range(filler)])
        yield from _emit(keys)


def _emit(lines):
    for line in lines:
        yield from line
        yield Segment.line()


def render_sidebar(state: TUIState) -> Panel:
    count = len(state.get_filtered_and_sorted_notebooks())
    # Focus border only where j/k moves this list; one focused pane at a time.
    overlay = state.selecting_sources or state.selecting_artifact or state.editing_context
    focused = state.current_view == View.NOTEBOOK_LIST and not overlay
    return panel(_NotebookList(state), f"Notebooks {count}", focused=focused)
