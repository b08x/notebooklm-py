import concurrent.futures
import logging
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from rich.console import Console
from rich.layout import Layout
from rich.live import Live

from .cache import TUICache
from .keypress import get_keys, handle_key, raw_terminal, suspend_raw_terminal
from .layout import build_layout
from .logging_bridge import install_tui_log_handler
from .renderers import (
    render_footer,
    render_header,
    render_jobs,
    render_main,
    render_modebar,
    render_sidebar,
)
from .renderers.factcheck import render_factcheck
from .renderers.ingest import render_ingest
from .state import Mode, TUIState, View
from .theme import THEME
from .views import corpus_view
from .views.notebook_list import load_notebooks_sync

logger = logging.getLogger(__name__)


def uses_legacy_assessment(state: TUIState) -> bool:
    """Fact-check mode shows the audio-assessment panes while that flow is active."""
    return state.mode == Mode.FACT_CHECK and bool(state.assessment_state)


def layout_mode(state: TUIState) -> Mode:
    """Which layout shape ``state`` renders into (legacy assessment uses the default)."""
    return Mode.NOTEBOOKS if uses_legacy_assessment(state) else state.mode


def layout_for_mode(cache: dict[Mode, Layout], mode: Mode) -> Layout:
    """Return the cached layout for ``mode``, building it on first use."""
    if mode not in cache:
        cache[mode] = build_layout(mode)
    return cache[mode]


def update_layout(layout, state):
    layout["header"].update(render_header(state))
    layout["modebar"].update(render_modebar(state))

    shape = layout_mode(state)
    if shape == Mode.JOBS:
        jobs_panel, jobs_detail = render_jobs(state)
        layout["jobs_list"].update(jobs_panel)
        layout["jobs_detail"].update(jobs_detail)
    elif shape == Mode.INGEST:
        tree, kids, detail = render_ingest(state)
        layout["ingest_tree"].update(tree)
        layout["ingest_children"].update(kids)
        layout["ingest_detail"].update(detail)
    elif shape == Mode.FACT_CHECK:
        claims, sift, evidence = render_factcheck(state)
        layout["fc_claims"].update(claims)
        layout["fc_sift"].update(sift)
        layout["fc_evidence"].update(evidence)
    else:
        layout["sidebar"].update(render_sidebar(state))

        results_panel, detail_panel = render_main(state)
        layout["content"]["results"].update(results_panel)
        layout["content"]["detail"].update(detail_panel)

    layout["footer"].update(render_footer(state))


def _run_editor_handoff(state: TUIState, live: Live) -> None:
    """Suspend the Live display, edit the compiled prompt in ``$EDITOR``, resume.

    Requested via ``state.compiler_state["edit_requested"]`` — the key handler
    never touches the terminal itself (fact 6). The edit lands in the preview
    marked ``edited`` and is never written back to the YAML or the template.
    """
    from .views.compiler_gen import apply_editor_result, edit_prompt_via_editor

    cs = state.compiler_state
    prompt = cs.get("prompt")
    if not prompt:
        return

    live.stop()
    try:
        with suspend_raw_terminal():
            result = edit_prompt_via_editor(prompt)
    finally:
        live.start(refresh=True)
    apply_editor_result(state, result)


def _start_job_queue(state: TUIState) -> None:
    """Connect to Redis, recover interrupted jobs, start the worker pool.

    Raises ``RedisUnavailable`` when Redis is down; ``run_tui`` turns that into
    a non-zero exit before the full-screen display opens (fact 39).
    """
    from .jobs import JobRunner, JobStore, connect, resolve_handler

    store = JobStore(connect())
    interrupted = store.mark_interrupted_on_startup()
    if interrupted:
        logger.warning("Marked %d job(s) interrupted from a previous session", interrupted)

    # dspy.configure is main-thread only; capture the LM here and let each
    # worker bind it with dspy.context (CLAUDE.md hard rule).
    lm = None
    try:
        from notebooklm._app.assessment import setup_dspy_router

        lm, _ = setup_dspy_router()
    except Exception as e:  # assessment extra missing or no API key
        logger.warning("DSPy LM unavailable for jobs: %s", e)

    runner = JobRunner(
        store, resolve_handler, consume_token=state.consume_token, state=state, lm=lm
    )
    runner.start()
    state.job_store = store
    state.job_runner = runner
    state.refresh_jobs_snapshot(max_age=0)


def run_tui(download_dir: str | None = None) -> None:
    state = TUIState()
    if download_dir:
        state.download_dir = download_dir

    from .jobs import RedisUnavailable

    try:
        _start_job_queue(state)
    except RedisUnavailable as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(2) from e

    # Route logging into the Logs view (`L`) instead of stdout/stderr, which
    # would corrupt the full-screen Live render below.
    install_tui_log_handler(state.log_records)

    console = Console(theme=THEME)

    # Initialize persistent cache
    cache = TUICache()
    state.tui_cache = cache
    state.notebook_summaries = cache.get_all_summaries()
    state.notebook_stats = cache.get_all_artifact_stats()
    cached_notebooks = cache.get_notebooks()
    if cached_notebooks:
        state.notebooks = cached_notebooks
        state.selected_notebook = getattr(cached_notebooks[0], "id", None)

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    # Load initial state
    with console.status("Loading notebooks...", spinner="dots"):
        load_notebooks_sync(state)

    layouts: dict[Mode, Layout] = {}
    layout = layout_for_mode(layouts, layout_mode(state))

    # Initial render
    update_layout(layout, state)

    # We use a short wait so that background tasks and UI updates feel responsive
    with raw_terminal(), Live(layout, console=console, auto_refresh=False, screen=True) as live:
        try:
            # Force first render
            live.refresh()
            corpus_loading = False
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

                if state.curation_task and state.curation_task.done():
                    state.curation_task = None
                    state_changed = True

                if state.compiler_task and state.compiler_task.done():
                    state.compiler_task = None
                    state_changed = True

                # The Compiler view's workers advance phase/spinner/elapsed
                # time with no keypress to trigger a redraw (fact 9).
                if state.current_view == View.COMPILER and state.compiler_state.get("phase") in (
                    "compiling",
                    "submitted",
                    "generating",
                    "downloading",
                ):
                    state_changed = True

                # $EDITOR handoff — outside the Live refresh, in cooked mode.
                if state.current_view == View.COMPILER and state.compiler_state.get(
                    "edit_requested"
                ):
                    state.compiler_state["edit_requested"] = False
                    _run_editor_handoff(state, live)
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

                # Curation workers (remove/add/delete/archive) mutate
                # state.curation in place the same way; the archive progress
                # display must advance without a keypress (fact 15).
                if state.curation and (
                    state.curation.get("busy") or state.curation.get("mode") == "archive_progress"
                ):
                    state_changed = True

                # Job workers write progress to Redis with no keypress to
                # trigger a redraw; re-read the job list while any is active.
                if state.job_store is not None:
                    before = [(j.id, j.status, j.percent, j.phase) for j in state.jobs_snapshot]
                    state.refresh_jobs_snapshot()
                    after = [(j.id, j.status, j.percent, j.phase) for j in state.jobs_snapshot]
                    if before != after or state.running_jobs():
                        state_changed = True

                # Ingest / Fact-check data loads on a worker thread; redraw
                # while a query is pending and once more when it lands.
                was_loading = corpus_loading
                if state.mode == Mode.INGEST:
                    corpus_view.load_ingest(state)
                    corpus_view.load_children(state)
                elif state.mode == Mode.FACT_CHECK and not uses_legacy_assessment(state):
                    corpus_view.load_claims(state)
                corpus_loading = corpus_view.is_loading(state)
                if corpus_loading or was_loading:
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
                    target = layout_for_mode(layouts, layout_mode(state))
                    if target is not layout:
                        layout = target
                        live.update(layout)
                    update_layout(layout, state)
                    live.refresh()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                cache.save_summaries(state.notebook_summaries)
            except Exception:
                pass
            executor.shutdown(wait=False)
            if state.job_runner is not None:
                state.job_runner.stop()
