# Audio Overview Assessment Pipeline

## Goal
Wire the existing NLP preprocessing pipeline (hybrid/structural chunking, spaCy annotation,
fact-checking) into the TUI's assessment view end-to-end, so selecting a notebook's generated
audio overview transcribes it via the existing transcription adapters, ingests it as a real
source under the notebook, and renders it in the Assessment view with colored entity
highlighting and fact-check gutters — replacing the current hardcoded-sample-text stub.

## Shared Understanding
The specific requirements and facts dictating this work are tracked in [facts.md](facts.md).

## Execution Plan
The step-by-step approach — including the notebook-detail entry point, the `_app`-layer
orchestration, transcript ingestion via `IngestionService`, entity/gutter rendering, and the
opt-in persisted fact-check action — is tracked in [plan.md](plan.md).

## Done Condition
This goal is considered done when, from the notebook detail view, a user can select a
notebook with a generated audio overview, trigger "Assess Audio Overview," see the real
transcript (sourced via `TranscriptionService`) chunked with color-coded entities and neutral
fact-check gutters in the Assessment view, run an opt-in fact-check per chunk that persists
its result to the `clauses` table and updates the gutter (with a clear UI warning when the
SIFT framework is unavailable), and get a real LLM-suggested score/feedback — all verified by
`uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports && uv run
pytest` passing locally with the `assessment` extra installed.
