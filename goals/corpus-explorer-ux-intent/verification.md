# Verification: Corpus Explorer QA remediation inside current tabs

Manual and automated verification record for `goal.md`. Updated as execution proceeds.

## Step 0 — Baseline (2026-10-12)

- Working tree at start: clean; the Step 0 precondition edits were already committed as `bfd6d025` ("feat(ui): map empty state, runs table scroll, contrast fixes").
- `ux-qa.mp4` is not present anywhere in the repo; no `.gitignore` change needed.
- Baseline commands (all exit 0):
  - `uv run pytest tests/server tests/unit/_app -q` → **456 passed** in 119.76s
  - `cd web && pnpm test` → **67 passed** (17 files), 4.03s
  - `cd web && pnpm typecheck` → **clean** (no output, exit 0)
- Follow-up goal stub created: `goals/corpus-explorer-workflow-ia/README.md` (fact 28).

## Steps 1–8 (commits)

| Step | Commit | Facts |
| --- | --- | --- |
| 1 Notebook title storage | `8fc44eab` | 1, 2 |
| 2 Per-clause SFL progress | `68922452` | 10 |
| 3 SFL job tracing and logs | `7b2ccf23` | 16, 17, 18 |
| 4 Jobs store, TagSflButton, jobs tray | `ad72e428` | 11–15, 18 |
| 5 Titles everywhere | `e9e31e7b` | 3, 4, 5 |
| 6 Browse columns | `f043ee6f` | 6–9 |
| 7 Map zoom, pan, legend, explainer | `5a4c2b72` | 19–24 |
| 8 URL state, history, breadcrumbs | `694a36b0` | 25–27 |

## Step 9 — Full verification (2026-10-12)

Commits: `f35a10ca` (polish, e2e specs, fixture title, rebuilt bundle) and the
follow-up coverage commit that adds this record.

### Fixes found during verification

- `pnpm e2e` failed 5/6 on the populated corpus: the specs selected the
  fixture notebook by its id, but Step 5 labels the facet by title (`nb-e2e
  untitled`) and the facet shows only the top 8 of 12 notebooks. The seed script
  now stores a title (`Fixture notebook nb-e2e`) and the specs expand the facet
  (`web/e2e/helpers.ts`).
- The column-resize spec measured the handle's x position; the Text column is
  the `1fr` grid track, so widening Document moves its left edge and the handle
  stays put. The spec now measures the header cell width. The zoom spec now
  polls `data-k` instead of reading it once.
- CI-equivalent pytest failed on a missing `soundfile` (environment: fixed by the
  canonical `uv sync --frozen … --extra assessment`) and on
  `docs/architecture.md` freshness (`_app/notebook_titles.py` was undocumented;
  added).
- Fact 29: the Map legend buttons lacked `active:scale-[0.96]`; added.
- Fact 14: the job-finished query invalidation moved from an inline `useEffect`
  in `App.tsx` into `useJobInvalidation()` so the DetailPane test exercises the
  same code App mounts.
- Coverage audit: 1 fact without a test (12) and 13 partially covered; tests
  added for facts 1, 3, 4, 5, 6, 11, 12, 13, 14, 15, 19, 20, 21, 22.

### Final command results (all exit 0)

| Command | Result |
| --- | --- |
| `cd web && pnpm typecheck` | clean |
| `cd web && pnpm test` | 22 files, **108 passed** |
| `cd web && E2E_PORT=8801 PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium pnpm e2e` | **6 passed** (45.3s), against the rebuilt bundle |
| `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports` | Success: no issues in 456 source files |
| `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` | 17371 passed, 64 skipped, 1 xfailed; coverage **93.06%** |

E2E runs on port 8801 (`E2E_PORT`) because a stale `notebooklm-server` held 8799
during the session.

### Fact → test map

| Fact | Automated check(s) |
| --- | --- |
| 1 | `tests/server/test_corpus_routes.py::test_ingest_writes_notebook_title`, `::test_notebook_titles_stored_live_and_failure` |
| 2 | `tests/server/test_corpus_routes.py::test_notebook_titles_stored_live_and_failure` (no signed-in client) |
| 3 | `FiltersPane.test.tsx` — title label, title tooltip, no visible UUID |
| 4 | `RowMeta.test.tsx`, `SearchResults.test.tsx`, `DetailPane.test.tsx` (titles in the chunk meta line), `Breadcrumbs.test.tsx`; Runs view: `Views.test.tsx` asserts the document title column ("Deep dive"; the view has no notebook column). The command palette lists only tabs and actions, so it shows no ids at all. |
| 5 | `FiltersPane.test.tsx` (untitled notebook), `RowMeta.test.tsx` (untitled notebook and document), `Views.test.tsx` |
| 6 | `BrowseTable.test.tsx` (every resizable header has a handle; Document drag), `e2e/ux.spec.ts` browse drag — **see deviation below** |
| 7, 9 | `BrowseTable.test.tsx` (sizing and visibility restored from storage) |
| 8 | `BrowseTable.test.tsx`, `e2e/ux.spec.ts` (double-click reset) |
| 10 | `tests/unit/test_sfl_tagging.py` (single-child and multi-parent progress), `tests/server/test_corpus_routes.py::test_sfl_run_for_document_scope` |
| 11 | `DetailPane.test.tsx` (running state n/N + elapsed), `TagSflButton.test.tsx` |
| 12 | `factcheck/FactCheck.test.tsx` — gate Tag first shows 2/5, stage text, elapsed |
| 13 | `JobsTray.test.tsx` (kind, label, progress, elapsed 01:15, outcome) |
| 14 | `DetailPane.test.tsx` — job finish re-fetches the chunk and shows the new SFL tag |
| 15 | `JobsTray.test.tsx` (error in tray and on button), `TagSflButton.test.tsx` |
| 16, 17 | `tests/unit/_app/test_background.py` (one `job.sfl_tag` root span; INFO/ERROR lines with job id) |
| 18 | `tests/unit/_app/test_background.py`, `JobsTray.test.tsx` (trace link) |
| 19 | `Views.test.tsx` (cursor-anchored zoom, drag pan), `e2e/ux.spec.ts` (wheel zoom + Reset) |
| 20, 21, 22, 23 | `Views.test.tsx` (legend titles + counts, isolate/restore, explainer clauses, tooltip) |
| 24 | `e2e/smoke.spec.ts` map point click |
| 25, 26 | `src/state/url.test.ts`, `e2e/ux.spec.ts` history |
| 27 | `Breadcrumbs.test.tsx`, `e2e/ux.spec.ts` history |
| 30 | the command table above |

### Manual facts

- **28** — `TABS` in `web/src/state/url.ts` is Search, Browse, Map, Runs,
  Fact-check; `goals/corpus-explorer-workflow-ia/README.md` records the follow-up.
- **29** — new controls (`Breadcrumbs`, `JobsTray`, `TagSflButton` via `Button`,
  `MapView` legend/reset, `BrowseTable` columns menu) use `duration-150`, named
  `transition-[…]` properties and `active:scale-[0.96]`;
  `web/src/test/stack.test.ts` guards `transition: all` and the button press
  scale. The one `duration-300` in the workbench (`FactCheckView` progress bar)
  predates this goal.

### Deviation: fact 6

Fact 6 says *every* Browse column has a resize handle. Two columns do not: the
row-selection checkbox column and the Chunk text column, which is the flexible
`minmax(0,1fr)` track that absorbs the remaining width (it changes width
whenever another column is resized). All six data columns (#, Document, Kind,
Len, Quality, Fact-check) have handles. Left as designed pending a decision.

### QA replay of the six observations (fact 31)

Automated replay in a real browser (Playwright, Chromium) plus a live SFL job.
No human screen-by-screen walkthrough of the original video was performed.

| # | Observation | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Notebooks/documents shown as UUIDs | does not reproduce | e2e page snapshots show titles in the Notebook facet; `GET /v1/corpus/notebooks` on a live server returned stored titles |
| 2 | Browse columns fixed | does not reproduce | `e2e/ux.spec.ts` drag + double-click reset |
| 3 | No SFL progress | does not reproduce | live job `cf751657` streamed `tagging`, `parent 1/1`, `tagging clause 1/1`, `parent done` |
| 4 | SFL jobs untraced / unlogged | does not reproduce | trace URL below; server log (with `NOTEBOOKLM_LOG_LEVEL=INFO`): `job_id=cf751657 kind=sfl_tag started`, `parent 1/1 tagged=1 failed=0`, `done` |
| 5 | Map not zoomable, no legend/explanation | does not reproduce | `e2e/ux.spec.ts` wheel zoom + Reset; `e2e/smoke.spec.ts` point click |
| 6 | No URL state / Back button | does not reproduce | `e2e/ux.spec.ts` history spec (Back/Forward, deep-link reload) |

SFL job Langfuse trace: <http://tinybot:3000/trace/131e16171d73cfb2286e8a71df1d87a3>
(job `cf751657`, 1 chunk, `{"tagged": 1, "failed": 0}`; host answered HTTP 307).

Note: the package logger defaults to WARNING, so the per-job INFO lines appear
only when the server runs with `NOTEBOOKLM_LOG_LEVEL=INFO`.
