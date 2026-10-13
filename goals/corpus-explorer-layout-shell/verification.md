# Verification Record: Corpus Explorer Layout Shell and Review Screen

## Step 0: Baseline

- `uv run pytest tests/server tests/unit/app tests/unit/_app -n auto -q`: exit 0 (1461 passed)
- `cd web && pnpm test`: exit 0 (22 files, 108 passed)
- `cd web && pnpm typecheck`: exit 0
- `cd web && pnpm e2e`: exit 0 (6 passed)

## Step 1: Backend Routes
- Added `documents` and `document_clauses` in `src/notebooklm/_app/corpus_explorer.py`.
- Added `GET /v1/corpus/documents` and `GET /v1/corpus/documents/{document_id}/clauses` in `src/notebooklm/server/routes/corpus.py`.
- Added unit tests in `tests/unit/app/test_corpus_explorer.py` (`test_documents_and_clauses_queries`).
- Added route tests in `tests/server/test_corpus_routes.py` (`test_documents_and_document_clauses_routes`).
- `uv run pytest tests/unit/app/test_corpus_explorer.py tests/server/test_corpus_routes.py`: passed.
- `uv run mypy src/notebooklm`: passed (0 issues in 447 files).

## Breakpoints verification (by-eye checks)

- [x] 1399px vs 1400px: Inspector drawer vs 4-column visible layout
  - At 1400px: Inspector panel is displayed inline on the right (360px default, resizable 320–480px with drag handle). The 4-column layout (Sidebar, Document List, Document View, Inspector) is fully visible. Header does not show the inspector drawer trigger button.
  - At 1399px: Inspector column collapses from the inline layout into a slide-over sheet drawer (`Drawer side="right"`). The header reveals `header-inspector-drawer-btn` with panel icon to open the inspector drawer on demand. Clicking opens dialog sheet with dark backdrop; pressing Escape or clicking backdrop dismisses it cleanly. Verified in Vitest and Playwright e2e (`web/e2e/review.spec.ts`).

- [x] 1023px vs 1024px: Document list drawer vs visible column
  - At 1024px: Document list is displayed inline at 320px width on the left of Document View, grouped under "Collection:" headers with collapse chevron, card list, search input, and filter tabs (All, Untagged, Tagged, Fact-checked).
  - At 1023px: Document list column collapses into a slide-over drawer (`Drawer side="left"`). Header reveals `header-list-drawer-btn`. Clicking opens 320px left drawer containing search input, filter tabs, collection headers, and virtualized document cards. Selecting a document or pressing Escape closes the drawer. Verified in Vitest and Playwright e2e (`web/e2e/review.spec.ts`).

- [x] 767px vs 768px: Sidebar drawer vs 64px rail
  - At 768px: Sidebar is displayed inline as a 64px icon rail (expandable to 256px with labels via toggle button), showing Review, Search, Browse, Map, Runs, Fact-check, and Settings navigation items.
  - At 767px: Sidebar disappears from inline layout. Header reveals `header-sidebar-drawer-btn` (menu hamburger icon). Clicking opens 256px left drawer showing the full navigation list. Verified in Vitest and Playwright e2e (`web/e2e/review.spec.ts`).

## Document walkthrough

- [x] Read continuous text:
  - Selected document renders document title in header and reading text capped at 72ch width (`max-w-[72ch]`).
  - Clauses are rendered as inline interactive spans with sentence boundaries intact and background tinting for SFL-tagged clauses (`bg-primary/10`).
- [x] Collapse chunks (Collapse all, Collapse unflagged, Expand all):
  - Chunks are preceded by a sticky chunk header with chunk number, clause count, tagged count, fact-check count, and toggle chevron.
  - Clicking chunk toggle chevron toggles individual chunk between full prose and single-line summary with ellipsis (`{chunk.clauses[0].text} ...`).
  - Clicking "Collapse all" collapses all chunks to single-line summaries; persisted in `localStorage["corpus-explorer:doc-collapsed:<docId>"]`.
  - Clicking "Collapse unflagged" collapses only clean/unflagged chunks, keeping any chunks with contradicted or unverified verdicts visible.
  - Clicking "Expand all" restores full prose across all chunks.
- [x] Tag a clause & inspect:
  - Clicking any clause span highlights it (`bg-primary/25 ring-1 ring-primary/60`), updates URL to `/ui/review?chunk=<external_id>`, and loads chunk details in Inspector.
  - Inspector header displays document title, Chunk number, Clause number, and close button.
  - Tabs (Context, Linguistics, Similar, Raw) provide full inspectability.
  - Pinned footer (~120px) shows SFL tag status ("Tagged" / "Untagged") with "Tag SFL" button (`data-testid="tag-sfl"`), and Fact-check status with badge and "Fact-check" button (`data-testid="inspector-factcheck-btn"`).
  - Clicking "Tag SFL" issues `POST /v1/corpus/sfl/runs` with `{ scope: { external_ids: [...] } }`.
- [x] Jump from right-edge marker strip:
  - Right-edge vertical marker strip renders colored ticks positioned proportionally to clause positions (green for supported, amber for unverified, red for contradicted, primary for SFL-tagged).
  - Clicking a tick jumps directly to that clause, expanding its parent chunk if collapsed, scrolling it into view, and opening it in the inspector.
- [x] Keyboard navigation:
  - Arrow Down and Arrow Up move clause selection between visible clauses, automatically skipping collapsed chunks.

## Final verification checks

- [x] `cd web && pnpm typecheck && pnpm test && pnpm e2e`: Passed (29 Vitest test files / 147 unit tests, 8 Playwright e2e tests, 0 TS errors).
- [x] `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`: Passed (0 issues in 456 source files).
- [x] `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90`: Passed (17,372 passed, total coverage 93.00% >= 90%).
- [x] `uv run ruff check .` and `uv run ruff format --check .`: Passed.
- [x] Bundle committed in `src/notebooklm/server/static/ui` on `development`.
