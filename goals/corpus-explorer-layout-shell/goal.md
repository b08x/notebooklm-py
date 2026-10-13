# Goal: Corpus Explorer layout shell and Review screen

Rebuild the Corpus Explorer web UI (`web/`) around the frame of the syncopated-context-compiler (SCC) Review screen, so the corpus can be read and judged document by document:

- a left sidebar replaces the header tabs (256px with labels, 64px icon-only);
- a new Review screen shows four regions: sidebar, document list grouped by collection, document view, inspector;
- the document view shows one document as reading text, grouped by chunk, with SFL tints, fact-check markers and collapsible chunks;
- the inspector keeps the Context, Linguistics, Similar and Raw tabs and adds a pinned footer for tagging and fact-checking the selected clause;
- regions collapse into drawers at 1400px (inspector), 1024px (list) and 768px (sidebar);
- a new `GET /v1/corpus/documents` route feeds the list.

The existing Search, Browse, Map, Runs and Fact-check screens, their data layer and tests are kept. SCC's Dexie storage, AI provider settings and Express server are not carried over. The layout is the foundation for a source-agnostic explorer, so the interface says "Collection", not "Notebook".

The workflow-based navigation (Curate → Tag → Verify → Explore) stays in `goals/corpus-explorer-workflow-ia/`; the sidebar's section labels are where it will attach.

- Shared understanding: [facts.md](facts.md)
- Interview record: [decisions.md](decisions.md)
- Execution plan: [plan.md](plan.md)
- Evidence log: `verification.md` (created during execution)

## Done condition

- All facts in `facts.md` hold.
- Facts about layout, collapse, selection, persistence and the new endpoint are covered by passing Vitest, pytest or Playwright checks.
- `cd web && pnpm typecheck && pnpm test && pnpm e2e`, `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`, and `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` all exit 0.
- The rebuilt bundle in `src/notebooklm/server/static/ui` is committed on `development`.
- `verification.md` records the by-eye check at 1399/1400, 1023/1024 and 767/768 px and a walkthrough of one real document (tag a clause, read, collapse chunks, jump from the marker strip).
