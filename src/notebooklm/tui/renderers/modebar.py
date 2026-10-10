from rich.panel import Panel
from rich.text import Text

from ..state import MODE_LABELS, Mode, TUIState
from ._widgets import panel


def mode_label(mode: Mode, state: TUIState) -> str:
    """Mode name for the bar; Jobs shows the running count when any job is active."""
    label = MODE_LABELS[mode]
    if mode == Mode.JOBS:
        running = state.running_jobs()
        if running:
            label += f" ({running}▸)"
    return label


def render_modebar(state: TUIState) -> Panel:
    """One-line mode bar; the active mode is highlighted with the ``selected`` style."""
    bar = Text(no_wrap=True, overflow="ellipsis")
    for mode in Mode:
        if mode.value > 1:
            bar.append(" │ ", style="subtle")
        active = mode == state.mode
        bar.append(str(mode.value), style="key")
        bar.append(f" {mode_label(mode, state)}", style="selected" if active else "muted")
    return panel(bar)
