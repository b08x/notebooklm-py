import concurrent.futures
import time

from rich import box
from rich.console import Group
from rich.layout import Layout
from rich.panel import Panel
from rich.text import Text
from rich.tree import Tree

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

            sys_inst = state.assessment_state.get("system_instructions", "")
            context = state.assessment_state.get("notebook_context", "")

            results = []
            framework_available = True

            for completed, chunk in enumerate(chunks_with_ids, start=1):
                # Update status
                state.assessment_state["fact_check_status"] = f"Checking: {chunk.text[:50]}..."

                result = await run_fact_check_for_chunk(
                    chunk.clause_external_id, chunk.text, sys_inst, context
                )

                # Stream the result to the chunk immediately
                chunk.fact_check_passed = result.passed
                results.append(result)
                framework_available = framework_available and result.framework_available
                state.assessment_state["fact_check_status"] = f"Completed {completed}/{len(chunks_with_ids)} checks..."

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

    def render(self):
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

            def make_sparkline(pct, width=20):
                chars = " ▂▃▄▅▆▇█"
                pct = max(0, min(100, pct))
                total_eighths = int((pct / 100) * width * 8)
                full_blocks = total_eighths // 8
                remainder = total_eighths % 8

                res = "█" * full_blocks
                if full_blocks < width:
                    res += chars[remainder]
                    res += " " * (width - full_blocks - 1)
                return res

            # Header Table
            header_table = Table(show_header=False, box=None, expand=True, padding=(0, 2))
            header_table.add_column(justify="left")
            header_table.add_column(justify="left")

            acc_bar_str = make_sparkline(accuracy_pct, 23)
            prog_bar_str = make_sparkline(progress_pct, 23)

            r1_c1 = Text.from_markup(f"[bold primary] [✔] CHUNK PROGRESS [/] [primary]{prog_bar_str}[/] {int(progress_pct)}% [[foreground]{completed}/{total}[/]]")
            r1_c2 = Text.from_markup(f"[bold accent] [⏱] ELAPSED TIME [/]  [foreground]{timer_str}[/]")

            r2_c1 = Text.from_markup(f"[bold success] [★] ACCURACY RATIO [/] [success]{acc_bar_str}[/] {int(accuracy_pct)}%")
            r2_c2 = Text.from_markup(f"[bold error] [⚠] UNVERIFIED   [/]  [foreground]{failed} Claims[/]")

            header_table.add_row(r1_c1, r1_c2)
            header_table.add_row(r2_c1, r2_c2)

            header_panel = Panel(
                header_table,
                box=box.ROUNDED,
                border_style="primary",
                padding=(1, 2)
            )

            # Active claim panel
            hitl_prompt = assessment_state.get("hitl_prompt")
            if hitl_prompt:
                chunk_text = hitl_prompt.get("chunk", "")
                active_claim = Panel(
                    Text.from_markup(f"[warning]Meta-Dialogue / Satire Detected![/]\n\n[foreground italic]\"{chunk_text}\"[/]\n\n[bold]Skip fact-checking for this chunk?[/]\nPress [bold success]y[/] to bypass, [bold error]n[/] to force fact-check, or [bold accent]s[/] to toggle Auto-Skip."),
                    title="⚠ HUMAN-IN-THE-LOOP REQUIRED",
                    title_align="left",
                    border_style="warning",
                    box=box.HEAVY,
                    padding=(1, 2)
                )
            else:
                current_chunk = assessment_state.get("current_chunk_text", "Waiting for chunks...")
                active_claim = Panel(
                    Text(f'"{current_chunk}"', style="foreground italic", justify="left"),
                    title="📝 ACTIVE TRANSCRIPT CLAIM",
                    title_align="left",
                    border_style="primary",
                    box=box.ROUNDED,
                    padding=(1, 2)
                )

            # Stream panel
            ticker_stream = assessment_state.get("ticker_stream", [])
            log_tree = Tree("")
            log_tree.hide_root = True

            items_to_show = list(reversed(ticker_stream[-6:])) if ticker_stream else []

            if not items_to_show:
                node = log_tree.add(Text("⏳ EVALUATING CURRENT CHUNK", style="muted"))
                node.add(Text("Checking external knowledge bases and indexed sources...", style="muted"))
            else:
                for i, item in enumerate(items_to_show):
                    if isinstance(item, dict):
                        is_passed = item.get("passed", True)
                        cit = item.get("citations", "")
                    else:
                        is_passed = "✓" in item
                        cit = item

                    mark = "✓ VERIFIED" if is_passed else "✗ CONTRADICTION FOUND"
                    color = "success" if is_passed else "error"
                    conf = "94" if is_passed else "--"

                    node_text = Text.from_markup(f"[bold {color}]{mark}[/] [muted]─[/] [bold primary]CONFIDENCE: {conf}%[/] [muted]─ PANEL \\[{completed - i:03d}][/]")
                    node = log_tree.add(node_text)

                    if cit:
                        node.add(Text(f"Source: {cit[:150]}...", style="foreground"))
                    else:
                        node.add(Text("Checking external knowledge bases and indexed sources...", style="muted"))

            stream_panel = Panel(
                log_tree,
                title="📚 VERIFIED EVIDENCE LOG STREAM",
                title_align="left",
                border_style="muted",
                box=box.ROUNDED,
                padding=(1, 2)
            )

            assessment_dash = Layout()
            assessment_dash.split_column(
                Layout(header_panel, name="header", size=6),
                Layout(name="body")
            )
            assessment_dash["body"].split_row(
                Layout(active_claim, name="claim_pane"),
                Layout(stream_panel, name="log_pane")
            )

            current_sfl = assessment_state.get("current_chunk_sfl")
            if current_sfl:
                from rich.table import Table

                sfl_table = Table(show_header=True, box=box.SIMPLE_HEAD, expand=True)
                sfl_table.add_column("Metafunction", style="muted", width=15)
                sfl_table.add_column("Parsing / Tagging", style="foreground")

                ideational = current_sfl.get("ideational", {})
                interpersonal = current_sfl.get("interpersonal", {})

                parts = ideational.get("participants", [])
                procs = ideational.get("processes", [])
                circs = ideational.get("circumstances", [])

                sfl_table.add_row("Participants", f"[primary]{', '.join(parts) if parts else 'None'}[/]")
                sfl_table.add_row("Processes", f"[success]{', '.join(procs) if procs else 'None'}[/]")
                sfl_table.add_row("Circumstances", f"[warning]{', '.join(circs) if circs else 'None'}[/]")
                sfl_table.add_row("Tenor", f"[accent]{interpersonal.get('tenor', 'N/A')}[/]")
                sfl_table.add_row("Mood", f"[accent]{interpersonal.get('mood', 'N/A')}[/]")
                sfl_table.add_row("Modality", f"[accent]{interpersonal.get('modality', 'N/A')}[/]")

                sfl_panel = Panel(
                    sfl_table,
                    title="🔍 SFL METAFUNCTION TAGGING",
                    title_align="left",
                    border_style="magenta",
                    box=box.ROUNDED,
                    padding=(1, 2)
                )
            else:
                sfl_panel = Panel(
                    Text("Waiting for SFL parsing...", style="muted"),
                    title="🔍 SFL METAFUNCTION TAGGING",
                    title_align="left",
                    border_style="muted",
                    box=box.ROUNDED,
                    padding=(1, 2)
                )

            return assessment_dash, sfl_panel
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
