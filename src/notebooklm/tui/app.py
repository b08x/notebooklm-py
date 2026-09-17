from rich.console import Console
from rich.live import Live

from .keypress import get_keys, handle_key, raw_terminal
from .layout import build_layout
from .logging_bridge import install_tui_log_handler
from .renderers import (
    render_footer,
    render_header,
    render_main,
    render_sidebar,
)
from .state import TUIState, View
from .theme import THEME
from .views.notebook_list import load_notebooks_sync


def update_layout(layout, state):
    layout["header"].update(render_header(state))
    layout["sidebar"].update(render_sidebar(state))

    results_panel, detail_panel = render_main(state)
    layout["content"]["results"].update(results_panel)
    layout["content"]["detail"].update(detail_panel)

    layout["footer"].update(render_footer(state))


def run_tui(download_dir: str | None = None) -> None:
    state = TUIState()
    if download_dir:
        state.download_dir = download_dir

    # Route logging into the Logs view (`L`) instead of stdout/stderr, which
    # would corrupt the full-screen Live render below.
    install_tui_log_handler(state.log_records)

    console = Console(theme=THEME)

    import json
    from pathlib import Path

    cache_file = Path.home() / ".notebooklm" / "tui_cache.json"
    if cache_file.exists():
        try:
            state.notebook_summaries = json.loads(cache_file.read_text())
        except Exception:
            pass

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

                if state.summary_task and state.summary_task.done():
                    state.summary_task = None
                    state_changed = True

                if state.stats_task and state.stats_task.done():
                    state.stats_task = None
                    state_changed = True

                if state.source_fetch_task and state.source_fetch_task.done():
                    state.source_fetch_task = None
                    state_changed = True

                # Background ingestion/assessment and the Logs view both mutate
                # state from a worker thread with no keypress to trigger a
                # redraw — poll them each tick so progress and new log lines
                # appear live instead of only on the next keystroke.
                if (
                    state.current_view == View.LOGS
                    or state.background_task
                    and not state.background_task.done()
                ):
                    state_changed = True

                # Auto-refresh if tokens replenish enough to unpause, or meter changes
                state.update_tokens()
                if not hasattr(state, "_last_rendered_tokens"):
                    state._last_rendered_tokens = int(state.api_tokens)
                elif int(state.api_tokens) != state._last_rendered_tokens:
                    state._last_rendered_tokens = int(state.api_tokens)
                    state_changed = True
                elif state.current_view == View.NOTEBOOK_LIST and state.selected_notebook:
                    current_summary = state.notebook_summaries.get(state.selected_notebook)

                    # Unpause logic
                    if current_summary == "Paused: Waiting for API capacity...":
                        if state.api_tokens >= 1.0:
                            state_changed = True

                if state_changed:
                    update_layout(layout, state)
                    live.refresh()
        except KeyboardInterrupt:
            pass
        finally:
            import json
            from pathlib import Path

            cache_file = Path.home() / ".notebooklm" / "tui_cache.json"
            try:
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                # Only save actual summaries, not placeholders
                to_save = {
                    k: v
                    for k, v in state.notebook_summaries.items()
                    if not v.startswith("Loading")
                    and not v.startswith("Paused")
                    and not v.startswith("Waiting for scroll")
                    and "Error loading summary" not in v
                }
                if cache_file.exists():
                    existing = json.loads(cache_file.read_text())
                    existing.update(to_save)
                    to_save = existing
                cache_file.write_text(json.dumps(to_save))
            except Exception:
                pass
