# Goal: Corpus Explorer QA remediation inside current tabs

Fix the six observations from the `ux-qa.mp4` QA session in the Corpus Explorer web workbench (`/ui`) and keep the current tabs (Search, Browse, Map, Runs, Fact-check):

- show notebooks and documents by title everywhere;
- make the Browse table columns resizable and hideable;
- show live per-clause SFL tagging progress, plus a jobs tray;
- give every SFL job a Langfuse trace and log lines;
- add zoom, pan, a legend and an explanation to the Map;
- add URL-backed browser history and breadcrumbs.

This is the first stage of organizing the UX by user workflow. The workflow-based navigation restructure (Curate → Tag → Verify → Explore) is a separate follow-up goal (`goals/corpus-explorer-workflow-ia/`).

- Shared understanding: [facts.md](facts.md) (31 facts; automated-verification flags in [facts.meta.json](facts.meta.json))
- Execution plan: [plan.md](plan.md) (steps 0–9, approved)
- Evidence log: `verification.md` (created during execution)

## Done condition

The goal is done when all of the following are true:
- All 31 facts in `facts.md` hold.
- Every fact marked `automatedVerification: true` is covered by a passing Vitest, pytest or Playwright check.
- `pnpm typecheck && pnpm test && pnpm e2e`, `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`, and the CI-equivalent `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` all exit 0.
- The rebuilt bundle in `src/notebooklm/server/static/ui` is committed on `development`.
- `verification.md` records a manual re-run of the QA video script in which none of the six observations reproduces, including one SFL job's Langfuse trace URL.
