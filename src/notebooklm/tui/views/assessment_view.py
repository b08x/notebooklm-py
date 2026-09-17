import concurrent.futures

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
    bg_task = getattr(state, "background_task", None)
    if bg_task is not None and not bg_task.done():
        return

    chunks = state.assessment_state.get("chunks", [])
    chunks_with_ids = [c for c in chunks if getattr(c, "clause_external_id", None)]
    if not chunks_with_ids:
        return

    def run():
        import asyncio

        async def _run_all():
            from notebooklm._app.assessment import run_fact_check_for_chunk

            results = []
            for chunk in chunks_with_ids:
                result = await run_fact_check_for_chunk(
                    chunk.clause_external_id, chunk.text
                )
                results.append(result)
            return results

        return asyncio.run(_run_all())

    def on_done(future):
        try:
            results = future.result()
        except Exception as e:
            state.error_message = f"Fact-check failed: {e}"
            return

        by_id = {r.clause_external_id: r for r in results}
        framework_available = True
        for chunk in chunks_with_ids:
            result = by_id.get(chunk.clause_external_id)
            if result is None:
                continue
            chunk.fact_check_passed = result.passed
            framework_available = framework_available and result.framework_available
        state.assessment_state["fact_check_framework_available"] = framework_available

    state.background_task = _fact_check_executor.submit(run)
    state.background_task.add_done_callback(on_done)


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
            loading_message = assessment_state.get("loading_message", "Loading...")
            import time
            start_time = assessment_state.setdefault("start_time", time.time())
            elapsed = time.time() - start_time
            mins, secs = divmod(int(elapsed), 60)
            timer_str = f"{mins:02d}:{secs:02d}"

            frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
            frame = frames[int(elapsed * 10) % len(frames)]

            from rich.align import Align
            from rich.console import Group
            from rich.text import Text

            content = Group(
                Align.center(Text(f"{frame} {loading_message}", style="yellow bold")),
                Align.center(Text(f"\nElapsed time: {timer_str}", style="dim")),
                Align.center(Text("\nThis may take a minute depending on hardware...", style="dim italic"))
            )

            loading_panel = Panel(
                Align.center(content, vertical="middle"),
                title="Assessment in Progress",
                border_style="yellow",
                style="main",
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
