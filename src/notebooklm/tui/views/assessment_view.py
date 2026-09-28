import concurrent.futures
import time

from rich.console import Group
from rich.layout import Layout
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from notebooklm._app.assessment import run_assessment_scoring

from ..renderers._widgets import key_hints, panel

_assessment_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
_fact_check_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

#: Per-entity-label style, used by :func:`_render_chunk_text`. Falls back to
#: ``ENTITY_STYLE_DEFAULT`` for any label not listed here.
ENTITY_STYLES = {
    "PERSON": "entity.person",
    "ORG": "entity.org",
    "DATE": "entity.time",
    "GPE": "entity.group",
    "TIME": "entity.time",
    "MONEY": "entity.money",
    "NORP": "entity.group",
    "LOC": "entity.group",
}
ENTITY_STYLE_DEFAULT = "entity.default"


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
            download_dir = getattr(state, "download_dir", None) or os.path.expanduser(
                "~/NotebookLM"
            )
            artifacts_dir = os.path.join(download_dir, "artifacts")

            report_path = generate_assessment_report(
                artifact_id=artifact_id,
                assessment_state=state.assessment_state,
                scoring_result=res,
                output_dir=artifacts_dir,
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
    chunks_with_ids = [
        c
        for c in chunks
        if getattr(c, "clause_external_id", None) and getattr(c, "fact_check_passed", None) is None
    ]
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
                state.assessment_state["fact_check_status"] = (
                    f"Completed {completed}/{len(chunks_with_ids)} checks..."
                )

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
        return Text("?", style="subtle")
    if not framework_available:
        return Text("✓*" if passed else "✗*", style="warning")
    return Text("✓", style="success") if passed else Text("✗", style="error")


def _bar(pct: float, width: int, style: str) -> Text:
    """Eighth-block progress bar with a subtle track."""
    chars = " ▏▎▍▌▋▊▉"
    pct = max(0.0, min(100.0, pct))
    eighths = int(pct / 100 * width * 8)
    full, rem = divmod(eighths, 8)
    text = Text(no_wrap=True)
    text.append("█" * full, style=style)
    if full < width:
        text.append(chars[rem], style=style)
        text.append("░" * (width - full - 1), style="subtle")
    return text


def _metric(label: str, value: Text) -> Text:
    text = Text(no_wrap=True)
    text.append(f"{label:<10}", style="label")
    text.append_text(value)
    return text


def _badges(items, style: str) -> Text:
    if not items:
        return Text("none", style="subtle")
    if isinstance(items, str):
        items = [items]
    text = Text()
    for i, item in enumerate(items):
        if i:
            text.append("  ")
        text.append(str(item), style=style)
    return text


def _labeled_block(label: str, value: str) -> Group:
    return Group(Text(label, style="heading"), Text(str(value), style="foreground"), Text(""))


class AssessmentView:
    def __init__(self, state):
        self.state = state

    def render(self):
        assessment_state = getattr(self.state, "assessment_state", {})
        mode = assessment_state.get("assessment_mode", "audio")
        mode_label = "Source Assessment" if mode == "sources" else "Audio Assessment"
        claim_title = "Active source claim" if mode == "sources" else "Active transcript claim"

        if assessment_state.get("is_loading"):
            return self._render_live(assessment_state, claim_title)

        audio_meta = assessment_state.get("audio_metadata", "No Audio Metadata Available.")
        sys_inst = assessment_state.get("system_instructions", "No System Instructions Available.")
        chunks = assessment_state.get("chunks", ["No Source Chunks Available."])
        llm_score = assessment_state.get("llm_score", "LLM Score Pending...")
        framework_available = assessment_state.get("fact_check_framework_available", True)
        fact_status = assessment_state.get("fact_check_status", "Not started.")

        metadata_label = "Source Metadata" if mode == "sources" else "Audio Output Metadata"
        # User and model data is placed in Text objects, never interpolated
        # into markup, so brackets in a transcript cannot break rendering.
        left_items: list = []
        if not framework_available:
            left_items.append(
                Text(
                    "⚠ SIFT framework not found — fact-check results are "
                    "unverified (always pass)\n",
                    style="warning",
                )
            )
        left_items += [
            _labeled_block(metadata_label, audio_meta),
            _labeled_block("System Instructions", sys_inst),
            _labeled_block("Suggested Score", llm_score),
            _labeled_block("Fact-Check Status", fact_status),
            key_hints(
                [("enter", "score"), ("f", "fact-check"), ("j/k", "scroll"), ("esc", "back")]
            ),
        ]
        left_panel = panel(Group(*left_items), "Assessment Controls", focused=True)

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

        right_panel = panel(
            Group(*renderables) if renderables else Text(""),
            f"{mode_label} — Contextualized Source Chunks (Scroll: {scroll_offset})",
        )

        return left_panel, right_panel

    def _render_live(self, assessment_state, claim_title):
        start_time = assessment_state.setdefault("start_time", time.time())
        mins, secs = divmod(int(time.time() - start_time), 60)

        metrics = assessment_state.get("metrics", {})
        completed = metrics.get("completed", 0)
        total = metrics.get("total", 0)
        passed = metrics.get("passed", 0)
        failed = metrics.get("failed", 0)

        progress_pct = (completed / total * 100) if total > 0 else 0
        accuracy_pct = (passed / completed * 100) if completed > 0 else 100

        header_table = Table.grid(expand=True, padding=(0, 3))
        header_table.add_column(ratio=1)
        header_table.add_column(ratio=1)
        progress = _bar(progress_pct, 20, "primary")
        progress.append(f" {int(progress_pct)}%  {completed}/{total}", style="foreground")
        accuracy = _bar(accuracy_pct, 20, "success")
        accuracy.append(f" {int(accuracy_pct)}%", style="foreground")
        header_table.add_row(
            _metric("Progress", progress),
            _metric("Elapsed", Text(f"{mins:02d}:{secs:02d}", style="foreground")),
        )
        header_table.add_row(
            _metric("Accuracy", accuracy),
            _metric(
                "Unverified",
                Text(f"{failed} claims", style="error" if failed else "foreground"),
            ),
        )
        header_panel = panel(header_table, "Assessment Running", focused=True, padding=(1, 2))

        hitl_prompt = assessment_state.get("hitl_prompt")
        if hitl_prompt:
            prompt = Text()
            prompt.append("Meta-dialogue or satire detected.\n\n", style="warning")
            prompt.append(f'"{hitl_prompt.get("chunk", "")}"\n\n', style="foreground italic")
            prompt.append("Skip fact-checking for this chunk?\n\n", style="heading")
            prompt.append_text(
                key_hints([("y", "skip"), ("n", "fact-check"), ("s", "toggle auto-skip")])
            )
            active_claim = panel(prompt, "⚠ Input required", focused=True, padding=(1, 2))
        else:
            current_chunk = assessment_state.get("current_chunk_text", "Waiting for chunks...")
            active_claim = panel(
                Text(f'"{current_chunk}"', style="foreground italic"), claim_title, padding=(1, 2)
            )

        log_tree = Tree("", guide_style="subtle", hide_root=True)
        ticker_stream = assessment_state.get("ticker_stream", [])
        items_to_show = list(reversed(ticker_stream[-6:])) if ticker_stream else []

        if not items_to_show:
            log_tree.add(Text("Evaluating current chunk…", style="muted"))
        for i, item in enumerate(items_to_show):
            if isinstance(item, dict):
                is_passed = item.get("passed", True)
                cit = item.get("citations", "")
            else:
                is_passed = "✓" in item
                cit = item

            node_text = Text(no_wrap=True)
            if is_passed:
                node_text.append("✓ verified", style="success")
            else:
                node_text.append("✗ contradiction", style="error")
            node_text.append(f"   chunk {completed - i:03d}", style="muted")
            node = log_tree.add(node_text)
            if cit:
                snippet = cit if len(cit) <= 150 else cit[:149] + "…"
                node.add(Text(snippet, style="foreground"))

        stream_panel = panel(log_tree, "Evidence", padding=(1, 2))

        assessment_dash = Layout()
        assessment_dash.split_column(
            Layout(header_panel, name="header", size=6), Layout(name="body")
        )
        assessment_dash["body"].split_row(
            Layout(active_claim, name="claim_pane"), Layout(stream_panel, name="log_pane")
        )

        current_sfl = assessment_state.get("current_chunk_sfl")
        if current_sfl:
            sfl_table = Table.grid(expand=True, padding=(0, 2))
            sfl_table.add_column("Metafunction", style="label", width=14, no_wrap=True)
            sfl_table.add_column("Parsing / Tagging")

            ideational = current_sfl.get("ideational", {})
            interpersonal = current_sfl.get("interpersonal", {})

            sfl_table.add_row(
                "Participants", _badges(ideational.get("participants", []), "entity.person")
            )
            sfl_table.add_row("Processes", _badges(ideational.get("processes", []), "entity.org"))
            sfl_table.add_row(
                "Circumstances", _badges(ideational.get("circumstances", []), "entity.time")
            )
            for key in ("tenor", "mood", "modality"):
                sfl_table.add_row(key.title(), _badges(interpersonal.get(key, "N/A"), "foreground"))
            sfl_panel = panel(sfl_table, "SFL metafunctions", padding=(1, 2))
        else:
            sfl_panel = panel(
                Text("Waiting for SFL parsing…", style="muted"), "SFL metafunctions", padding=(1, 2)
            )

        return assessment_dash, sfl_panel
