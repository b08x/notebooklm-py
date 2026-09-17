from rich.align import Align
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState

_LEVEL_STYLES = {
    "CRITICAL": "error",
    "ERROR": "error",
    "WARNING": "warning",
    "INFO": "foreground",
    "DEBUG": "muted",
}

#: How many buffered lines to actually render; the buffer itself
#: (``TUIState.log_records``) holds up to 500 so nothing is dropped before you
#: switch to this view, but only the tail needs to be drawn each frame.
_VISIBLE_LINES = 200


def render_logs(state: TUIState) -> tuple[Panel, Panel]:
    records = list(state.log_records)
    body = Text()
    if not records:
        body.append(
            "No log output yet. Log level defaults to INFO — set "
            "NOTEBOOKLM_TUI_LOG_LEVEL=DEBUG before launching for more detail.",
            style="muted",
        )
    else:
        for level, line in records[-_VISIBLE_LINES:]:
            body.append(f"{line}\n", style=_LEVEL_STYLES.get(level, "foreground"))

    logs_panel = Panel(
        body,
        title=f"Logs ({len(records)} buffered, showing last {min(len(records), _VISIBLE_LINES)})",
        border_style="border",
        style="main",
        padding=(1, 2),
    )
    hint_panel = Panel(
        Align.center("[Esc] return to the previous view", vertical="middle"),
        title="Details",
        border_style="border",
    )
    return logs_panel, hint_panel
