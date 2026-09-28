import datetime
import re

from rich.panel import Panel
from rich.tree import Tree

from ..state import SORT_LABELS, TUIState


def _parse_domain_tag(title: str) -> tuple[str, str, str]:
    """Extract [DOMAIN] tag, assign a color style, and return (rendered_chip, clean_title, raw_tag)."""
    match = re.match(r"^\[([A-Za-z0-9_-]+)\]\s*(.*)$", title)
    if not match:
        return "", title, ""

    raw_tag = match.group(1).upper()
    clean_title = match.group(2)

    # Deterministic color mapping for common prefixes
    if "GEMINI" in raw_tag:
        style = "cyan"
    elif "CLAUDE" in raw_tag:
        style = "magenta"
    elif "SFL" in raw_tag or "ENG" in raw_tag:
        style = "yellow"
    elif "TEST" in raw_tag or "DEV" in raw_tag:
        style = "green"
    else:
        style = "accent"

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
        badges.append("🎙️")
    if stats.get("has_notes") or stats.get("total_artifacts", 0) > 0:
        badges.append("📄")

    # Recent activity indicator (generated within last 48 hours)
    recent_ts = stats.get("recent_generated_at")
    if recent_ts:
        now_ts = datetime.datetime.now(datetime.timezone.utc).timestamp()
        if (now_ts - recent_ts) < 172800:  # 48 hours
            badges.append("⚡")

    return "".join(badges)


def render_sidebar(state: TUIState) -> Panel:
    notebooks = state.get_filtered_and_sorted_notebooks()

    # Ensure selected notebook is within viewport
    visible_rows = 15
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

    # Slice notebooks for pagination
    sliced_notebooks = notebooks[state.scroll_offset : state.scroll_offset + visible_rows]

    # Header label with active sort and filter info
    sort_label = SORT_LABELS.get(state.sort_key, state.sort_key)
    filter_parts = []
    if state.search_query:
        typing_indicator = "..." if getattr(state, "searching", False) else ""
        filter_parts.append(f"🔍 '{state.search_query}{typing_indicator}'")
    elif getattr(state, "searching", False):
        filter_parts.append("🔍 typing...")

    if state.filter_has_audio:
        filter_parts.append("🎙️")
    if state.filter_min_sources:
        filter_parts.append("non-empty")

    filter_desc = f" [dim][{', '.join(filter_parts)}][/dim]" if filter_parts else ""
    tree = Tree(f"📚 [b]Notebooks[/b] [dim]({sort_label})[/dim]{filter_desc}")

    for nb in sliced_notebooks:
        raw_title = getattr(nb, "title", "Unknown") or "Unknown"
        is_selected = nb.id == state.selected_notebook
        sources_cnt = getattr(nb, "sources_count", 0)
        try:
            sources_val = int(sources_cnt) if sources_cnt is not None else 0
            sources_str = f"{sources_val:>2}"
        except (ValueError, TypeError):
            sources_str = str(sources_cnt)

        chip, clean_title, _ = _parse_domain_tag(raw_title)
        badges = _get_artifact_badges(nb.id, state)
        badges_str = f" {badges}" if badges else ""

        # Truncate clean title if long so badges and count fit nicely
        max_title_len = 24
        if len(clean_title) > max_title_len:
            truncated_title = clean_title[: max_title_len - 1] + "…"
        else:
            truncated_title = clean_title

        style = "selected" if is_selected else "foreground"
        prefix = "▶" if is_selected else " "
        node_label = f"[{style}]{prefix} {chip}{truncated_title} ({sources_str}){badges_str}[/]"

        tree.add(node_label)

    if not notebooks:
        if state.search_query or state.filter_has_audio or state.filter_min_sources:
            tree.add("[muted]No matching notebooks.[/]")
        else:
            tree.add("[muted]No notebooks found.[/]")

    tree.add("")
    commands = tree.add("⚙️  [b]Commands[/b]")
    commands.add("[Enter] Select")
    commands.add(r"\[/] Search")
    commands.add(rf"\[s] Sort ({sort_label})")
    audio_flag = "✓" if state.filter_has_audio else " "
    commands.add(rf"\[o] Audio filter [{audio_flag}]")
    sources_flag = "✓" if state.filter_min_sources else " "
    commands.add(rf"\[z] Non-empty [{sources_flag}]")
    commands.add("[c] Chat")
    commands.add("[p] Prompt Compiler")
    commands.add("[A] Assessment")
    commands.add("[r] Refresh")
    commands.add("[q] Quit")

    return Panel(tree, title="Corpus & Actions", border_style="border")
