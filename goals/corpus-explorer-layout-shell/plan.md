# Plan: Corpus Explorer layout shell and Review screen

Facts: [facts.md](facts.md). Decisions: [decisions.md](decisions.md).

## Solution approach

Rebuild SCC's frame in `web/` as React components on the existing store, URL sync and React Query layer. Add one Review screen and two read-only backend routes. Leave the other five screens' internals unchanged.

| Need | Today in code | Change |
| --- | --- | --- |
| Sidebar navigation | `Header.tsx` renders `TABS` as header buttons; `App.tsx` grid is `48px / auto / 1fr / 28px` | New `Sidebar.tsx`; `App.tsx` becomes a flex row; `Header.tsx` shrinks to 40px and drops tabs |
| Review tab | `Tab` union in `state/url.ts` has five values | Add `review` and `settings` |
| Document list | No document endpoint; `facets().labels.document` has titles only | `GET /v1/corpus/documents` |
| Document text | Only `chunk_detail` and `browse` return clause data | `GET /v1/corpus/documents/{id}/clauses` returning chunks with their clauses |
| Responsive regions | Fixed `react-resizable-panels` percentages in `Workbench.tsx` | `useViewportTier()` hook plus Radix Dialog drawers (same base as `AskDrawer.tsx`) |
| Inspector | `DetailPane.tsx` (339 lines) shows one clause in four tabs | Reuse its tab bodies; add the header, resize handle and pinned footer; reuse `TagSflButton` |
| URL | `toUrl`/`fromUrl` encode tab, chunk, filters | Add `doc` handling for Review; the `chunk` parameter selects the clause |

**Precondition:** the working tree has only an untracked transcript file. Do not commit it.

## Ordered steps

### Step 0: Baseline
- Record `uv run pytest tests/server tests/unit/app tests/unit/_app -q` and `cd web && pnpm test && pnpm typecheck && pnpm e2e` exit codes in `verification.md`.
- Add the breakpoint constants file `web/src/lib/layout.ts` (`BP_INSPECTOR = 1400`, `BP_LIST = 1024`, `BP_SIDEBAR = 768`, `BP_SIDEBAR_DEFAULT = 1280`) so later steps import one source.

### Step 1: Backend routes (document list and document clauses)
- `src/notebooklm/_app/corpus_explorer.py`:
  - `documents(session, filters)`: one row per `Clause.document_id` with `document_id`, title (from `ChunkRun.params["title"]`), `notebook_id`, file type (from the asset or the source kind), clause count, tagged count (`Clause.sfl IS NOT NULL`), fact-checked count (distinct clauses with a `FactCheck` row).
  - `document_clauses(session, document_id)`: parent chunks in order, each with its clauses (`external_id`, `text`, `has_sfl`, latest fact-check verdict or null).
- `src/notebooklm/server/routes/corpus.py`: `GET /documents` (accepts the existing filters) and `GET /documents/{document_id}/clauses`. Collection titles come from the `corpus_notebooks` table, so the routes work with no signed-in client. Unknown document returns 404 using the existing `_not_found` pattern.
- Verify: tests in `tests/server/test_corpus_routes.py` and `tests/unit/_app/` using the existing fixture DB: counts match inserted rows, a document with no tagged clauses reports 0, an unknown id returns 404, titles come back without a client.

### Step 2: Shell: sidebar, 40px header, new tabs
- `state/url.ts`: add `review` and `settings` to `Tab` and `TABS`; add icons. Existing URLs keep working; `/ui` with no tab opens `review`.
- `features/Sidebar.tsx`: nav landmark, 256px or 64px, toggle button, width persisted under a `localStorage` key, default 64px below `BP_SIDEBAR_DEFAULT`; below `BP_SIDEBAR` it renders inside a Radix Dialog drawer.
- `features/Header.tsx`: 40px; remove the tab buttons; keep Search form and mode switch only when `tab === "search"`; keep Ask, theme toggle and the palette trigger.
- `App.tsx`: flex row (sidebar, then a grid `40px / auto / 1fr / 28px` column); move `Breadcrumbs` into the header.
- `features/SettingsView.tsx`: minimal stub with theme and "Forget token" (clears `getToken`) so the Settings entry is not dead.
- Update `CommandPalette.tsx` and `ShortcutSheet.tsx` for the new screens.
- Verify: Vitest for the sidebar toggle and persistence, default width below 1280px (mock `matchMedia`), tab links push history; Playwright smoke still reaches every old screen through the sidebar.

### Step 3: Responsive tiers and drawers
- `hooks/useViewportTier.ts`: returns `"wide" | "medium" | "narrow" | "tiny"` from `matchMedia` at the three breakpoints, updated on change.
- `features/Drawer.tsx`: shared Radix Dialog wrapper, side `left` or `right`, width 280px or 360px, backdrop, Escape and outside-click close, focus trap. Reuse the styling of `AskDrawer.tsx`.
- Header gets two buttons (list, inspector) shown only when that region is in a drawer.
- Verify: Vitest for the hook with a mocked `matchMedia` at each edge (1399/1400, 1023/1024, 767/768); the drawer closes on Escape.

### Step 4: Document list
- `lib/queries.ts`: `useDocuments(filters)` over `/v1/corpus/documents`.
- `features/review/DocumentList.tsx`: search field, filter tabs, collection groups with persisted open state, document cards with the status line, 320px; the list is virtualized with `@tanstack/react-virtual` (the median collection has 21 items, but the collection count is 371 and will grow).
- Selecting a document sets `filters.document_ids = [id]` and clears the open clause.
- Verify: Vitest for grouping, search filter, each filter tab, group collapse persistence, and the "Collection" label; a document card shows "untitled" with the short id when no title exists.

### Step 5: Document view
- `lib/queries.ts`: `useDocumentClauses(documentId)`.
- `features/review/DocumentView.tsx`: virtualized list of chunk headers and clause spans; tint for tagged clauses; verdict markers; chunk collapse; "Collapse all" and "Collapse unflagged"; per-document collapse state in `localStorage`; 72ch cap on prose; right-edge marker strip; arrow-key navigation that skips collapsed chunks.
- Use `@tanstack/react-virtual`, which is already in `web/package.json`.
- Verify: Vitest with a synthetic 1,600-clause document asserts that fewer than 100 DOM rows mount; collapse toggles, collapse-unflagged hides only chunks with no tagged or flagged clause, arrow keys skip collapsed chunks, marker click expands and scrolls (spy on `scrollToIndex`).

### Step 6: Inspector
- Extract the tab bodies from `DetailPane.tsx` into `features/review/inspector/*`; keep `DetailPane` working for the Search, Browse and Map screens by having it render the same extracted bodies.
- `features/review/Inspector.tsx`: header, tab bar, scrolling body, pinned footer (SFL state, verdict, `TagSflButton`, fact-check button using `startFactCheck`), empty state; left-edge drag handle (320–480px, persisted).
- In the `medium` tier it renders inside the right `Drawer` and opens on clause selection.
- Verify: Vitest for the empty state, the footer buttons calling the existing job and fact-check actions, width clamping and persistence, and the drawer opening on selection at 1200px.

### Step 7: Review screen assembly, URL and breadcrumbs
- `features/review/ReviewScreen.tsx`: composes list, document view and inspector by tier; flex row with `flex: 0 0 320px` list, `flex: 1 1 0; min-width: 0` document view, inspector as specified.
- `state/url.ts`: `/ui/review?doc=<id>&chunk=<clause>`; `popstate` restores both.
- `Breadcrumbs.tsx`: Collection › Document › Chunk, moved into the header.
- Verify: Vitest round-trip of `toUrl(fromUrl(x))` for review states; Playwright: open Review → pick a document → select a clause → Back → Forward; reload a deep URL.

### Step 8: Polish, build, full verification
- better-ui pass: named transition properties of 150ms or less, scale 0.96 on press, concentric radii on cards and drawers, 1px divider in the gutter, contrast of tints and markers in light and dark.
- Rebuild the bundle with `cd web && pnpm build` and commit the asset changes together.
- Run the full checks from the done condition; check exit status directly, not through a pipe.
- Manual: by-eye check at 1399/1400, 1023/1024 and 767/768 px; walkthrough of one real document (tag a clause, read, collapse chunks, jump from the marker strip); record results in `verification.md`.

## Risks and open questions

- **`fact_checks` has 0 rows.** Verdict markers, the "Fact-checked" tab and fact-checked counts can be tested only with fixture data until SIFT stores verdicts.
- **File type source.** The documents route needs a file type per document. If `LocalAsset` is not linked to the document id, the route derives it from the source kind and leaves "unknown" otherwise. Check the join in step 1.
- **Document view mixes chunk and clause ids.** The URL uses the existing clause external id for `chunk=`. Keep that name to preserve old URLs.
- **Settings screen** is a stub (theme, forget token). Its real contents are not decided.
- **Breakpoint values are estimates** from width arithmetic (sidebar 64 + list 320 + view ≈605 + inspector 360 + gutters 48 ≈ 1400px). They are constants, so a by-eye adjustment is a one-line change.
- **Header search** appears only on the Search screen; Review has its own list search. A global search is deferred.
- **Coverage gate:** new backend code needs tests to keep coverage at or above 90%; use the full extras install from CLAUDE.md.
