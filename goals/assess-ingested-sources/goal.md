# Goal: Assess Ingested Sources

## Articulated Goal

Refactor the assessment trigger so that when no audio overview exists, the pipeline falls back
to already-ingested source clauses in the database rather than failing. Both paths — audio
transcript and ingested sources — run through the same SFL + fact-check pipeline, with the
mode clearly labeled in the TUI and output reports.

## Shared Understanding

See [`facts.md`](./facts.md) for the full set of accepted facts governing this change.

## Execution Plan

See [`plan.md`](./plan.md) for the ordered implementation steps, file touch list, verification
commands, and risk table.

## Done Condition

- `run_source_assessment()` exists in `_app/assessment.py` and passes its unit tests.
- Triggering assessment on a notebook with ingested sources but no audio overview reaches
  the Assessment view successfully (no "no source chunks available" error).
- Triggering assessment on a notebook with no audio AND no ingested sources shows the
  correct error message without changing the view.
- The existing audio-based assessment path is unchanged and its tests continue to pass.
- `uv run pytest tests/unit/ -v` passes at or above 90% coverage.
- `uv run ruff check .` and `uv run mypy src/notebooklm` report no new errors.
