# Plan: Assess Ingested Sources

## Solution Approach

Add a new `run_source_assessment()` function in `_app/assessment.py` that loads already-ingested
`Clause` rows from the database and runs them through the same SFL + claim-detection + HITL
fact-check loop as `run_full_assessment()`, skipping all audio/transcription/diarization logic.
Modify `_assess_audio_overview_async()` in `notebook_detail.py` to fall back to
`run_source_assessment()` when no audio overview exists, and error out only when neither path
is available. No new keybinding, no new view — the existing `a` key path handles both modes.

**API cost constraint (from fact-11):** The default model is already
`deepseek/deepseek-v4-flash-0731` (very cheap via OpenRouter). The claim-detection pass
(`ClaimDetectorSignature`) skips fact-check LLM calls for non-factual chunks, bounding cost
naturally. No changes to model routing needed for MVP; the existing `NOTEBOOKLM_ASSESSMENT_MODEL`
env var gives operators a tuning knob.

---

## Ordered Steps

### Step 1 — Add `run_source_assessment()` to `_app/assessment.py`

**Files:** [`src/notebooklm/_app/assessment.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/_app/assessment.py)

**What it does:**
1. Calls `setup_dspy_router()` (same as `run_full_assessment`).
2. Fetches source IDs: `await client.sources.list(notebook_id)` → `[s.id for s in sources]`.
   - `Clause` has no `notebook_id` column, so source IDs from the API are the only scope key.
3. Queries `Clause` rows: `SELECT * FROM clauses WHERE document_id IN (source_ids)`.
4. If clauses list is empty: raises `ValueError("No ingested source clauses found for notebook
   {notebook_id}. Run 'Ingest Sources' first.")` — caller catches and maps to the error
   message in fact-8.
5. Resolves `system_instructions` via `resolve_notebook_context(client, notebook_id)` (or
   `context_override` if provided), empty string fallback.
6. Builds `source_metadata` JSON:
   ```json
   {"mode": "sources", "source_ids": [...], "source_count": N}
   ```
   This populates `AssessmentResult.audio_metadata` (fact-7).
7. Constructs `assessment_chunks` list from loaded clauses:
   - `text = clause.text`, `clause_external_id = clause.external_id`
   - `topic_id = -1`, `entities = []` (not set during ingest; safe default)
8. Runs the **same** SFL + claim-detection + HITL fact-check loop from `run_full_assessment`,
   with these differences:
   - `provider = "sources"` (no diarization branch is entered)
   - `_extract_speaker()` is not called (no diarization data)
   - `display_text = chunk.text` directly (no speaker prefix)
9. Returns `AssessmentResult(system_instructions=..., audio_metadata=source_metadata_json,
   transcript="", chunks=assessment_chunks, sfl_metrics=sfl_metrics)`.
   - `transcript=""` because there is no audio transcript; `sfl_metrics` from
     `analyze_transcript("")` (produces zero-counts, which is fine).

**SFL note:** `analyze_transcript("")` on an empty string gracefully returns zero-counts.
No special casing needed.

**Verification:**
```bash
uv run python -c "
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from notebooklm._app import assessment as m
# Quick smoke: run_source_assessment is importable
print(hasattr(m, 'run_source_assessment'))
"
```

---

### Step 2 — Refactor `_assess_audio_overview_async()` in `notebook_detail.py`

**Files:** [`src/notebooklm/tui/views/notebook_detail.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/views/notebook_detail.py)

**Current flow:**
```
if not artifact_id:
    audio_artifacts = await client.artifacts.list_audio(notebook_id)
    if not audio_artifacts:
        return {"error": "No generated audio overview found..."}   # ← hard fail
    artifact_id = audio_artifacts[-1].id
result = await run_full_assessment(...)
```

**New flow:**
```
if not artifact_id:
    audio_artifacts = await client.artifacts.list_audio(notebook_id)
    if audio_artifacts:
        artifact_id = max(audio_artifacts, key=...).id
        # fall through to run_full_assessment below
    else:
        # No audio — try source assessment path
        try:
            result = await run_source_assessment(
                client, session, notebook_id,
                context_override=context_override,
                progress_callback=progress_cb,
                state_callback=state_cb,
                hitl_callback=hitl_cb,
            )
            return {
                "assessment_state": {
                    "artifact_id": None,
                    "assessment_mode": "sources",
                    "system_instructions": result.system_instructions,
                    "audio_metadata": result.audio_metadata,
                    "chunks": result.chunks,
                    "sfl_metrics": result.sfl_metrics,
                    "scroll_offset": 0,
                }
            }
        except ValueError as exc:
            return {"error": str(exc)}

# existing audio path continues unchanged
result = await run_full_assessment(...)
return {
    "assessment_state": {
        "artifact_id": artifact_id,
        "assessment_mode": "audio",    # ← add this field (fact-9)
        ...
    }
}
```

**Import to add** at the top of the function body:
```python
from notebooklm._app.assessment import run_source_assessment
```
(lazy import inside the function avoids circular-import risk and matches the existing style.)

**Verification:**
```bash
uv run python -c "from notebooklm.tui.views.notebook_detail import _assess_audio_overview_async; print('ok')"
```

---

### Step 3 — Surface `assessment_mode` in the Assessment view

**Files:** [`src/notebooklm/tui/views/assessment_view.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/views/assessment_view.py)

**Change:** In `AssessmentView.render()`, update the right panel title to show the mode:
```python
mode = assessment_state.get("assessment_mode", "audio")
mode_label = "Source Assessment" if mode == "sources" else "Audio Assessment"
right_panel = Panel(..., title=f"{mode_label} — Contextualized Chunks (Scroll: {scroll_offset})")
```
And update the left panel's "Audio Output Metadata" label similarly when mode is `"sources"`.

This is the only TUI change needed; no new view or key is required.

**Verification:** Manual — trigger the source-assess path and confirm the panel titles update.

---

### Step 4 — Fix `generate_assessment_report()` for source mode

**Files:** [`src/notebooklm/_app/assessment.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/_app/assessment.py)

`generate_assessment_report()` uses `artifact_id` for the report filename. When `artifact_id`
is `None` (source mode), the filename would be `fact_check_report_None.md`. Guard it:
```python
safe_id = artifact_id or "sources"
report_path = os.path.join(output_dir, f"fact_check_report_{safe_id}.md")
```

Also update the report header to print the mode when known.

**Verification:**
```bash
uv run python -c "
from notebooklm._app.assessment import generate_assessment_report, ScoringResult
import tempfile, os
with tempfile.TemporaryDirectory() as d:
    p = generate_assessment_report(None, {'chunks': []}, ScoringResult([], '7', 'ok'), d)
    print(os.path.basename(p))   # should be fact_check_report_sources.md
"
```

---

### Step 5 — Unit tests

**Files:** [`tests/unit/app/test_source_assessment.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/tests/unit/app/test_source_assessment.py) *(new)*

Two tests modelled on the existing `test_assessment_context.py` style:

1. **`test_run_source_assessment_happy_path`**
   - Mock `client.sources.list` → returns two fake sources with `.id` fields.
   - Mock `session.execute` → returns fake `Clause` rows with `.text` and `.external_id`.
   - Stub `setup_dspy_router`, `resolve_notebook_context`, `analyze_transcript`, `SFLEngine`,
     `ClaimDetectorSignature`, `run_fact_check_for_chunk`.
   - Assert `AssessmentResult` is returned; `audio_metadata` JSON contains `"mode": "sources"`;
     `system_instructions` equals the mocked summary.

2. **`test_run_source_assessment_no_clauses_raises`**
   - Mock `client.sources.list` → returns sources.
   - Mock `session.execute` → returns empty rows.
   - Assert `ValueError` is raised with the expected message.

**Verification:**
```bash
uv run pytest tests/unit/app/test_source_assessment.py -v
```

---

### Step 6 — Run full test suite + linting

```bash
uv run pytest tests/unit/ -v
uv run pytest tests/_guardrails/ -v
uv run ruff check src/notebooklm/_app/assessment.py src/notebooklm/tui/views/notebook_detail.py
uv run ruff format src/notebooklm/_app/assessment.py src/notebooklm/tui/views/notebook_detail.py
uv run mypy src/notebooklm/_app/assessment.py src/notebooklm/tui/views/notebook_detail.py
```

---

## Risks and Open Questions

| Risk | Mitigation |
|---|---|
| `Clause` table has no `notebook_id` — must scope by source IDs from API | `client.sources.list()` is already used in `clause_search.py` for the same reason; same pattern applies |
| Source notebooks with many clauses → many LLM calls (claim-detection + fact-check) | Claim-detection short-circuits fact-check for non-factual chunks (HITL skip); `deepseek-flash-v4` is very cheap; HITL auto-skip mode reduces further |
| `AssessmentResult.transcript` is empty string for source mode | Not used in the fact-check loop; the report just prints it empty — acceptable for MVP |
| `sfl_metrics` from `analyze_transcript("")` returns zero-counts | Graceful; the loading view's sparkline shows 0 clauses which is accurate |
| `generate_assessment_report` called with `artifact_id=None` from `assessment_view.py` | Fixed in Step 4 |
