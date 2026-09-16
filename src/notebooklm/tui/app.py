from rich.console import Console
from rich.live import Live

from .keypress import get_keys, handle_key, raw_terminal
from .layout import build_layout
from .renderers import (
    render_footer,
    render_header,
    render_main,
    render_sidebar_commands,
    render_sidebar_notebooks,
)
from .state import TUIState
from .theme import THEME
from .views.notebook_list import load_notebooks_sync


def update_layout(layout, state):
    layout["header"].update(render_header(state))
    layout["sidebar"]["notebooks"].update(render_sidebar_notebooks(state))
    layout["sidebar"]["commands"].update(render_sidebar_commands(state))
    layout["main"].update(render_main(state))
    layout["footer"].update(render_footer(state))


def run_tui() -> None:
    state = TUIState()
    console = Console(theme=THEME)

    # Load initial state
    with console.status("Loading notebooks...", spinner="dots"):
        load_notebooks_sync(state)

    layout = build_layout()

    # Initial render
    update_layout(layout, state)

    # We use a short wait so that background tasks and UI updates feel responsive
    with raw_terminal(), Live(layout, console=console, auto_refresh=False, screen=True) as live:
        try:
            # Force first render
            live.refresh()
            while True:
                keys = get_keys()
                state_changed = False

                if keys:
                    for key in keys:
                        if not handle_key(key, state):
                            return  # Quit
                        state_changed = True

                # Check background tasks, etc.
                if state.background_task and state.background_task.done():
                    state.background_task = None
                    state_changed = True

                if state_changed:
                    update_layout(layout, state)
                    live.refresh()
        except KeyboardInterrupt:
            pass
