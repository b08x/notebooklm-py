from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.spinner import Spinner
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ..state import TUIState
from ..theme import COLORS
from ..views.compiler_gen import PROMPT_CHAR_WARNING
from ..views.compiler_view import load_compiler_configs
from ._widgets import panel

#: Lines of the compiled prompt rendered per redraw; the panel clips the rest,
#: so only the scroll window (fact 4) is ever laid out.
_PREVIEW_WINDOW = 48

_SPINNER_PHASES = ("compiling", "submitted", "generating", "downloading")


def char_count_style(count: int) -> str:
    """Warning style above the threshold, muted below it (fact 5)."""
    return "warning" if count > PROMPT_CHAR_WARNING else "muted"


def format_elapsed(started_at: float | None, now: float | None = None) -> str:
    """Elapsed generation time as ``mm:ss`` (fact 9)."""
    if started_at is None:
        return "00:00"
    import time

    elapsed = max(0.0, (now if now is not None else time.time()) - started_at)
    minutes, seconds = divmod(int(elapsed), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _target_notebook_title(state: TUIState) -> str | None:
    title = state.compiler_state.get("notebook_title")
    if title:
        return title
    if state.selected_notebook:
        for nb in state.notebooks:
            if getattr(nb, "id", None) == state.selected_notebook:
                return getattr(nb, "title", None)
    return None


def _is_matching_notebook(state: TUIState) -> bool:
    cs_nb = state.compiler_state.get("notebook_id")
    return not cs_nb or not state.selected_notebook or cs_nb == state.selected_notebook


def _render_compiler_dashboard(state: TUIState) -> Table:
    cs = state.compiler_state
    table = Table.grid(expand=True)
    table.add_column(width=16, no_wrap=True)
    table.add_column(ratio=1, no_wrap=True, overflow="ellipsis")

    target = _target_notebook_title(state)
    if target:
        table.add_row(
            Text("Target Notebook:", style="heading"), Text(f"→ {target}", style="success")
        )
    else:
        table.add_row(
            Text("Target Notebook:", style="heading"), Text("no notebook selected", style="warning")
        )

    target_id = state.selected_notebook
    if target_id:
        table.add_row(Text("Notebook ID:", style="muted"), Text(target_id, style="subtle"))

    table.add_row("", "")
    template = cs.get("template", "mr-and-mrs-language-model")
    audio_format = cs.get("audio_format", "default")
    audio_length = cs.get("audio_length", "default")

    table.add_row(Text("Template:", style="label"), Text(template, style="foreground"))
    table.add_row(Text("Audio Format:", style="label"), Text(audio_format, style="foreground"))
    table.add_row(Text("Audio Length:", style="label"), Text(audio_length, style="foreground"))
    table.add_row(Text("Extraction:", style="label"), Text("Chat RAG (Auto-Bind)", style="info"))

    table.add_row("", "")
    table.add_row(Text("Controls:", style="heading"), Text(""))
    table.add_row(Text("enter / c", style="key"), Text("Compile prompt from notebook"))
    table.add_row(Text("f", style="key"), Text("Cycle format (default/deep-dive/...)"))
    table.add_row(Text("l", style="key"), Text("Cycle length (default/short/long)"))
    table.add_row(Text("e", style="key"), Text("Edit in $EDITOR"))
    table.add_row(Text("g", style="key"), Text("Generate audio"))

    if _is_matching_notebook(state):
        error = cs.get("error")
        warning = cs.get("warning")
        if error:
            table.add_row("", "")
            table.add_row(Text("Error:", style="error"), Text(error, style="error"))
        elif warning:
            table.add_row("", "")
            table.add_row(Text("Warning:", style="warning"), Text(warning, style="warning"))

    return table


# Backward compatible alias for existing tests
_render_config_list = _render_compiler_dashboard


def _evidence_lines(state: TUIState) -> list[Text]:
    """One dimmed line per filled slot: ``agreement ← <clause id>: <text start>`` (fact 19)."""
    evidence = state.compiler_state.get("evidence") or {}
    lines = []
    for slot, clauses in evidence.items():
        if not clauses:
            continue
        ids = ", ".join(cid for cid, _ in clauses[:3])
        head_text = next(text for _, text in clauses)
        lines.append(Text(f"{slot} ← {ids}", style="subtle"))
        lines.append(Text(f"  {head_text[:48].replace(chr(10), ' ')}", style="subtle"))
    return lines


def _render_status(state: TUIState) -> Text | Spinner | None:
    cs = state.compiler_state
    phase = cs.get("phase")
    if phase in _SPINNER_PHASES:
        label = {
            "compiling": "compiling",
            "submitted": "submitted",
            "generating": "generating",
            "downloading": "downloading",
        }[phase]
        elapsed = format_elapsed(cs.get("started_at"))
        return Spinner("dots", text=Text(f" {label} · {elapsed}", style="info"), style="info")
    if phase == "done":
        return Text(f"done · {cs.get('mp3_path', '')}", style="success")
    if phase == "failed":
        parts = [Text("failed", style="error")]
        error = cs.get("error")
        if error:
            parts.append(Text(f" · {error}", style="error"))
        if cs.get("artifact_id"):
            parts.append(Text(f" · artifact {cs['artifact_id']}", style="error"))
        return Text.assemble(*parts)
    return None


def _render_preview_header(state: TUIState) -> Text:
    cs = state.compiler_state
    prompt = cs.get("prompt", "")
    header = Text(no_wrap=True, overflow="ellipsis")
    header.append(
        f"{cs.get('project', '?')} · {cs.get('notebook_title', '?')} · "
        f"{cs.get('audio_format', 'default')} · {cs.get('audio_length', 'default')} · "
    )
    header.append(f"{len(prompt)} chars", style=char_count_style(len(prompt)))
    if cs.get("edited"):
        header.append("  edited", style="warning")
    return header


def _render_prompt_body(state: TUIState) -> RenderableType:
    cs = state.compiler_state
    prompt = cs.get("prompt", "")
    scroll = cs.get("scroll", 0)
    lines = prompt.splitlines()
    window = "\n".join(lines[scroll : scroll + _PREVIEW_WINDOW])
    return Syntax(
        window,
        "markdown",
        word_wrap=True,
        theme="monokai",
        background_color=COLORS["background"],
    )


def _render_confirm_panel(state: TUIState) -> Panel:
    cs = state.compiler_state
    prompt = cs.get("prompt", "")
    rows = Table.grid(expand=True)
    rows.add_column(ratio=1)
    rows.add_row(Text("Send this prompt to NotebookLM?", style="heading"))
    rows.add_row(Text(f"notebook  {cs.get('notebook_title', '?')}", style="muted"))
    rows.add_row(Text(f"project   {cs.get('project', '?')}", style="muted"))
    rows.add_row(Text(f"format    {cs.get('audio_format', 'default')}", style="muted"))
    rows.add_row(Text(f"length    {cs.get('audio_length', 'default')}", style="muted"))
    rows.add_row(Text(f"chars     {len(prompt)}", style=char_count_style(len(prompt))))
    rows.add_row(Text(f"edited    {'yes' if cs.get('edited') else 'no'}", style="muted"))
    rows.add_row(Text(""))
    rows.add_row(Text("y send", style="key"), end_section=False)
    rows.add_row(Text("n cancel", style="key"))
    return panel(rows, "Confirm generate", focused=True)


def _render_detail(state: TUIState) -> Panel:
    cs = state.compiler_state
    matching = _is_matching_notebook(state)
    prompt = cs.get("prompt") if matching else None

    if matching and cs.get("confirm"):
        return _render_confirm_panel(state)

    if not prompt:
        preview = cs.get("preview") if matching else None
        if preview:
            return panel(Text(preview, style="foreground"), "Preview", focused=False)

        status = _render_status(state) if matching else None
        err = cs.get("error") if matching else None
        warn = cs.get("warning") if matching else None
        body: RenderableType = Text(
            err or warn or "Press Enter / c to compile prompt from the target notebook.",
            style="error" if err else "muted",
        )
        if status is not None:
            body = Group(body, status)
        return panel(body, "Preview")

    parts: list[RenderableType] = [_render_preview_header(state)]
    # The status line goes directly under the header: the prompt body is
    # longer than the panel, so anything appended after it (evidence, status)
    # would be clipped and hide the generation state (fact 9).
    status = _render_status(state)
    if status is not None:
        parts.append(status)
    if cs.get("error"):
        parts.append(Text(cs["error"], style="error"))
    if cs.get("warning"):
        parts.append(Text(cs["warning"], style="warning"))
    parts.append(_render_prompt_body(state))
    evidence = _evidence_lines(state)
    if evidence:
        parts.append(Text(""))
        parts.append(Text("Evidence", style="label"))
        parts.extend(evidence)
    return panel(Group(*parts), "Preview")


def render_compiler(state: TUIState) -> tuple[Panel, Panel]:
    if "configs" not in state.compiler_state:
        load_compiler_configs(state)

    results_panel = panel(_render_compiler_dashboard(state), "Compiler Dashboard", focused=True)
    detail_panel = _render_detail(state)

    return results_panel, detail_panel
