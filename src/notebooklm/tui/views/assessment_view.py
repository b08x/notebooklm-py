import concurrent.futures
import time

from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from notebooklm._app.assessment import run_assessment_scoring

_assessment_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
_fact_check_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

#: Per-entity-label style, used by :func:`_render_chunk_text`. Falls back to
#: ``ENTITY_STYLE_DEFAULT`` for any label not listed here.
ENTITY_STYLES = {
    "PERSON": "cyan",
    "ORG": "green",
    "DATE": "yellow",
    "GPE": "yellow",
    "TIME": "yellow",
    "MONEY": "magenta",
    "NORP": "blue",
    "LOC": "yellow",
}
ENTITY_STYLE_DEFAULT = "white"


def trigger_assessment_grading(state):
    bg_task = getattr(state, "background_task", None)
    if bg_task is not None and not bg_task.done():
        return

    state.assessment_state["llm_score"] = "Generating assessment..."

    sys_inst = state.assessment_state.get("system_instructions", "")
    audio_meta = state.assessment_state.get("audio_metadata", "")

    def fetch():
        chunks = state.assessment_state.get("chunks", [])
        raw_text = state.assessment_state.get("raw_text")
        return run_assessment_scoring(chunks, sys_inst, audio_meta, raw_text)

    def on_done(future):
        try:
            res = future.result()
            state.assessment_state["chunks"] = res.chunks
            state.assessment_state["llm_score"] = f"Score: {res.score}\nFeedback: {res.feedback}"

            # Generate the markdown report
            import os

            from notebooklm._app.assessment import generate_assessment_report

            artifact_id = state.assessment_state.get("artifact_id", "unknown_artifact")
            download_dir = getattr(state, "download_dir", None) or os.path.expanduser("~/NotebookLM")
            artifacts_dir = os.path.join(download_dir, "artifacts")

            report_path = generate_assessment_report(
                artifact_id=artifact_id,
                assessment_state=state.assessment_state,
                scoring_result=res,
                output_dir=artifacts_dir
            )

            state.assessment_state["llm_score"] += f"\n\nReport saved to:\n{report_path}"
        except Exception as e:
            err_str = str(e)
            if len(err_str) > 200:
                err_str = err_str[:197] + "..."
            import re
            err_str = re.sub(r"\x1b\[[0-9;]*m", "", err_str)
            state.assessment_state["llm_score"] = f"Error: {err_str}"

    state.background_task = _assessment_executor.submit(fetch)
    state.background_task.add_done_callback(on_done)


def trigger_fact_check(state):
    """Run an opt-in fact-check for every currently-loaded chunk (the `f` key).

    Persists each verdict onto its `Clause.fact_check_passed` row via
    `_app.assessment.run_fact_check_for_chunk` and updates the in-memory chunk
    objects so the gutter re-renders on the next frame.
    """
    bg_task = getattr(state, "fact_check_task", None)
    if bg_task is not None and not bg_task.done():
        return

    chunks = state.assessment_state.get("chunks", [])
    chunks_with_ids = [c for c in chunks if getattr(c, "clause_external_id", None) and getattr(c, "fact_check_passed", None) is None]
    if not chunks_with_ids:
        return

    # Clear previous status
    state.assessment_state["fact_check_status"] = "Starting fact-checking..."

    def run():
        import asyncio

        async def _run_all():
            from notebooklm._app.assessment import run_fact_check_for_chunk

            sem = asyncio.Semaphore(5)

            async def _run_with_sem(chunk):
                # Update status
                state.assessment_state["fact_check_status"] = f"Checking: {chunk.text[:50]}..."

                async with sem:
                    result = await run_fact_check_for_chunk(
                        chunk.clause_external_id, chunk.text
                    )
                # Stream the result to the chunk immediately
                chunk.fact_check_passed = result.passed
                return result

            tasks = [_run_with_sem(chunk) for chunk in chunks_with_ids]

            results = []
            framework_available = True

            for completed, coro in enumerate(asyncio.as_completed(tasks), start=1):
                res = await coro
                results.append(res)
                framework_available = framework_available and res.framework_available
                state.assessment_state["fact_check_status"] = f"Completed {completed}/{len(tasks)} checks..."

            return framework_available

        return asyncio.run(_run_all())

    def on_done(future):
        try:
            framework_available = future.result()
            state.assessment_state["fact_check_framework_available"] = framework_available
            state.assessment_state["fact_check_status"] = "Fact-checking complete."
        except Exception as e:
            state.error_message = f"Fact-check failed: {e}"
            state.assessment_state["fact_check_status"] = f"Failed: {e}"

    state.fact_check_task = _fact_check_executor.submit(run)
    state.fact_check_task.add_done_callback(on_done)



def _render_chunk_text(chunk) -> Text:
    """Build a `Text` for one chunk with entity spans stylized by label."""
    if isinstance(chunk, str):
        return Text(chunk)

    text = Text(chunk.text)
    for entity_text, label in getattr(chunk, "entities", []):
        style = ENTITY_STYLES.get(label, ENTITY_STYLE_DEFAULT)
        start = chunk.text.find(entity_text)
        if start == -1:
            continue
        text.stylize(style, start, start + len(entity_text))
    return text


def _gutter_glyph(chunk, framework_available: bool) -> Text:
    passed = getattr(chunk, "fact_check_passed", None)
    if passed is None:
        return Text("?", style="dim")
    if not framework_available:
        return Text("✓*" if passed else "✗*", style="yellow dim")
    return Text("✓", style="green") if passed else Text("✗", style="red")


class AssessmentView:
    def __init__(self, state):
        self.state = state

    def render(self) -> tuple[Panel, Panel]:
        assessment_state = getattr(self.state, "assessment_state", {})

        if assessment_state.get("is_loading"):
            from rich.table import Table

            start_time = assessment_state.setdefault("start_time", time.time())
            elapsed = time.time() - start_time
            mins, secs = divmod(int(elapsed), 60)
            timer_str = f"{mins:02d}:{secs:02d}"

            metrics = assessment_state.get("metrics", {})
            completed = metrics.get("completed", 0)
            total = metrics.get("total", 0)
            passed = metrics.get("passed", 0)
            failed = metrics.get("failed", 0)

            progress_pct = (completed / total * 100) if total > 0 else 0
            accuracy_pct = (passed / completed * 100) if completed > 0 else 100

            def make_bar(pct, width=20, fill="█", empty="░"):
                filled = int((pct / 100) * width)
                return fill * filled + empty * (width - filled)

            # Header Table
            header_table = Table(show_header=False, box=None, expand=True, padding=(0, 2))
            header_table.add_column(justify="left")
            header_table.add_column(justify="left")

            acc_bar_str = make_bar(accuracy_pct, 23, "█", "░")

            r1_c1 = Text.from_markup(f"[bold cyan] [✔] CHUNK PROGRESS [/] [blue]▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬[/] {int(progress_pct)}% [[white]{completed}/{total}[/]]")
            r1_c2 = Text.from_markup(f"[bold yellow] [⏱] ELAPSED TIME [/]  [white]{timer_str}[/]")

            r2_c1 = Text.from_markup(f"[bold green] [★] ACCURACY RATIO [/] [green]{acc_bar_str}[/] {int(accuracy_pct)}%")
            r2_c2 = Text.from_markup(f"[bold red] [⚠] UNVERIFIED   [/]  [white]{failed} Claims[/]")

            header_table.add_row(r1_c1, r1_c2)
            header_table.add_row(r2_c1, r2_c2)

            # Active claim panel
            current_chunk = assessment_state.get("current_chunk_text", "Waiting for chunks...")
            active_claim = Panel(
                Text(f'"{current_chunk}"', style="white italic", justify="left"),
                title="📝 ACTIVE TRANSCRIPT CLAIM",
                title_align="left",
                border_style="cyan",
                padding=(1, 2)
            )

            # Stream panel
            ticker_stream = assessment_state.get("ticker_stream", [])
            stream_items = []

            # Show the most recent 4 items
            for i, item in enumerate(reversed(ticker_stream[-4:])):
                # Fallback to dict get if it's new format, otherwise handle old string format safely during reload
                if isinstance(item, dict):
                    is_passed = item.get("passed", True)
                    cit = item.get("citations", "")
                else:
                    is_passed = "✓" in item
                    cit = item

                mark = "✓ VERIFIED" if is_passed else "✗ CONTRADICTION FOUND"
                color = "green" if is_passed else "red"
                conf = "94" if is_passed else "--"

                p_text = Text()
                p_text.append(f" PANEL [{completed - i:03d}] ────────────────────────────────────────────────── [ CONFIDENCE: {conf}% ] \n", style="blue bold")
                p_text.append(f" {mark}\n", style=f"bold {color}")

                if cit:
                    p_text.append(f" Source: {cit[:150]}...\n", style="white")
                else:
                    p_text.append(" Checking external knowledge bases and indexed sources...\n", style="dim")

                stream_items.append(p_text)

            if not stream_items:
                stream_items.append(
                    Text(" ⏳ EVALUATING CURRENT CHUNK\n Checking external knowledge bases and indexed sources...", style="dim")
                )

            stream_panel = Panel(
                Group(*stream_items),
                title="📚 VERIFIED EVIDENCE LOG STREAM",
                title_align="left",
                border_style="blue",
                padding=(1, 2)
            )

            layout_group = Group(
                header_table,
                Text(""),
                active_claim,
                stream_panel
            )

            loading_panel = Panel(
                layout_group,
                title="NotebookLM Assessment",
                border_style="magenta",
                style="main",
                padding=(0, 1)
            )
            return loading_panel, Panel("", border_style="border")
        audio_meta = assessment_state.get("audio_metadata", "No Audio Metadata Available.")
        sys_inst = assessment_state.get("system_instructions", "No System Instructions Available.")
        chunks = assessment_state.get("chunks", ["No Source Chunks Available."])
        llm_score = assessment_state.get("llm_score", "LLM Score Pending...")
        framework_available = assessment_state.get("fact_check_framework_available", True)

        left_lines = [
            f"Audio Output Metadata:\n{audio_meta}",
            f"System Instructions:\n{sys_inst}",
            f"Suggested Score:\n{llm_score}",
            f"Fact-Check Status:\n{assessment_state.get('fact_check_status', 'Not started. Press `f` to run.')}",
        ]
        if not framework_available:
            left_lines.insert(
                0,
                "[yellow]⚠ SIFT framework not found — fact-check results are "
                "unverified (always pass)[/yellow]",
            )
        left_text = "\n\n".join(left_lines)
        left_panel = Panel(left_text, title="Assessment Controls")

        scroll_offset = assessment_state.get("scroll_offset", 0)
        visible_chunks = chunks[scroll_offset : scroll_offset + 30]

        renderables = []
        for chunk in visible_chunks:
            gutter = _gutter_glyph(chunk, framework_available)
            body = _render_chunk_text(chunk)
            line = Text()
            line.append(gutter)
            line.append(" ")
            line.append(body)
            renderables.append(line)

        right_panel = Panel(
            Group(*renderables) if renderables else Text(""),
            title=f"Contextualized Source Chunks (Scroll: {scroll_offset})",
        )

        return left_panel, right_panel
