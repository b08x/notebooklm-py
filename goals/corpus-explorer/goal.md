# Goal: Corpus Explorer

Build a polished, feature-rich React web workbench, served by the existing `notebooklm-server` at `/ui`, for working with the chunk corpus in Postgres. Its features:
- hybrid RRF search with a per-leg score breakdown
- browsing, inspecting, correlating (similar items, near-duplicates, embedding map) and confirmed deletion of chunks
- answers grounded in retrieved chunks, through NotebookLM or a DSPy cross-notebook pipeline
- interactive fact-check runs with a Jev or rule-based gate, SIFT evidence and SFL panels.

Assessment (SFL tagging and fact-check) also becomes general: it works on any document in the corpus, and NotebookLM artifacts (audio and video transcribed after FLAC preparation, text artifacts converted directly) can be ingested with a checksum check that skips unchanged content.

- **Shared understanding:** [facts.md](facts.md): 63 accepted facts. [facts.meta.json](facts.meta.json) marks which need automated verification.
- **Execution plan:** [plan.md](plan.md): 13 ordered steps plus step 5b, each with verification commands, risks and out-of-scope notes.
- **Visual reference:** [mockups.html](mockups.html): direction **A · Workbench** and **A · Fact-check**.

## Done condition

The goal is done when:
- Every fact in `facts.md` holds. Each `[auto]` fact is backed by a passing automated check (pytest against the real Postgres, Vitest, or Playwright). Each `[manual]` fact has been verified by hand against the running app.
- `uv run ruff check .`, `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`, and `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` all exit 0.
- `pnpm -C web test`, `pnpm -C web build` and `pnpm -C web exec playwright test` all exit 0.
- A `/better-ui` review of `web/` ends in `Approve`.
