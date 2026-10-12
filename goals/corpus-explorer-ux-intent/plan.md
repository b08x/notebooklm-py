# Plan: Corpus Explorer QA remediation inside current tabs

Facts: [facts.md](facts.md) (31 facts, all accepted unedited).

## Solution approach

Fix each QA observation at the place in the code that causes it. Keep the five top-level tabs.

| QA observation | Cause in code | Fix |
| --- | --- | --- |
| UUID notebooks | Postgres has no corpus notebook titles; `FiltersPane.tsx:166` renders `shortId(v, 18)` | New `corpus_notebooks` title table, written at ingest and on every successful live list; one `useNotebookTitles()` hook used by every surface |
| Compressed table | `BrowseTable` has fixed `size` values and no resizing | Enable TanStack column resizing and visibility; persist both in `localStorage` |
| Progress not visible | `sfl_run` reports progress once per *parent*; `DetailPane.tagSfl` posts and toasts without following events | Per-clause progress callback; shared `TagSflButton` that follows `/jobs/{id}/events`; jobs tray in the footer |
| No logs or traces | `BackgroundJob` opens no `job_span` and has no logger | `JobRegistry.start(..., traced=True)` wraps the body in `job_span(kind, job_id=…)`; snapshot carries `trace_url`; INFO and ERROR logs |
| Map has no zoom or legend | Canvas with a fixed fit-to-bounds scale; header shows only "colored by X" | View transform (zoom and pan), legend with isolate, explainer line, document title in tooltip |
| No breadcrumbs or history | `actions.setTab` uses `history.replaceState`; the open chunk and filters are not in the URL | Two-way URL ↔ store sync with `pushState` for tab and chunk changes, a `popstate` handler, and a breadcrumb bar |

**Precondition:** the working tree already has uncommitted edits in `corpus.py`, `MapView.tsx`, `RunsView.tsx`, `index.css` and `test/setup.ts`, plus a rebuilt bundle. Step 0 commits them on their own so this goal's diffs are reviewable.

## Ordered steps

### Step 0: Baseline (all facts)
- Commit the existing working-tree edits as a separate commit on `development`. Do not commit `ux-qa.mp4`; add it to `.gitignore` or move it out of the repo.
- Record a baseline: `uv run pytest tests/server tests/unit/app tests/unit/_app -q`, `cd web && pnpm test && pnpm typecheck`.
- Create `goals/corpus-explorer-workflow-ia/README.md`, a stub for the follow-up goal (Curate → Tag → Verify → Explore), with a link back to this goal **(fact 28)**.
- **Verify:** baseline exit codes are recorded in `goals/corpus-explorer-ux-intent/verification.md`.

### Step 1: Notebook title storage (facts 1, 2)
- `src/notebooklm/db/models.py`: add `CorpusNotebook` (`__tablename__ = "corpus_notebooks"`: `notebook_id` PK String, `title` String not null, `updated_at` DateTime with `server_default=func.now()` and `onupdate`).
- `alembic/versions/<new>_corpus_notebook_titles.py`: `down_revision = "f2c1a7d4e9b0"`. Backfill from `archived_notebooks.title` and `removal_log.notebook_title` where they exist.
- `src/notebooklm/_app/corpus_explorer.py` (or a new `_app/notebook_titles.py`): `upsert_titles(session, {id: title})` and `stored_titles(session, ids)`.
- `src/notebooklm/server/routes/corpus.py`:
  - `GET /notebooks`: read stored titles first. When the live `client.notebooks.list()` succeeds, upsert the result and overlay it. A live failure leaves the stored titles in place.
  - The artifact ingest route (`/artifacts/{id}/ingest`): before ingesting, upsert the notebook title, taking it from `client.notebooks.get(notebook_id)` or from the list (best effort, inside a try block).
- **Verify:** add tests to `tests/server/test_corpus_routes.py`:
  - With no client, `/notebooks` returns a stored title.
  - A live list updates the stored row.
  - A live failure keeps the stored title.
  - Run `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` against the test DB.

### Step 2: Per-clause SFL progress (fact 10)
- `src/notebooklm/_app/sfl_tagging.py`: add an optional `child: Callable[[int, int, int], None] = lambda *_: None` to `GroupProgress`. It is called as `child(clause_number_overall, total, parent_number)` before each child's `_forward`, and again after the child finishes. The TUI handler keeps its current behavior because the default is a no-op.
- `corpus.py::sfl_run`: pass `child=` that calls `job.progress(f"tagging clause {k}/{N}", k-1, N)` before the clause and `job.progress(..., k, N)` after it.
- **Verify:** a unit test with a fake engine and 1 child produces progress events `tagging clause 1/1` with `done` 0 and then 1. With 3 children in 2 parents, the test asserts a monotonic `done` sequence 0…3. Existing TUI `sfl_tag` handler tests stay green.

### Step 3: SFL job observability (facts 16, 17, 18)
- `src/notebooklm/_app/background.py`:
  - Add `logger = logging.getLogger(__name__)` and `trace_id: str | None`.
  - Add `traced: bool` to `JobRegistry.start`. When it is true, `_run` wraps the body in `job_span(kind, job_id=self.id, label=self.label)` and stores the trace id.
  - Log INFO on start and finish and ERROR (with exception info) on failure. Every log line includes `job_id=` and `kind=`.
  - Add `trace_url` (from `tracing.trace_url`) to `snapshot()`.
- `corpus.py::sfl_run`: call `services.jobs.start("sfl_tag", label, run, traced=True)`. The per-parent `done` callback also logs INFO `sfl_tag job=<id> parent n/N tagged=… failed=…`.
- `asyncio.to_thread` copies contextvars, so DSPy spans created inside `_forward` nest under the job span. No `dspy.configure()` call is added (CLAUDE.md thread rule).
- **Verify:** pytest installs an OTel `TracerProvider` with an `InMemorySpanExporter`, runs a fake-engine SFL job, and asserts:
  - exactly one `job.sfl_tag` root span exists, and the engine call's span is its child;
  - `snapshot()["trace_url"]` ends with that trace id;
  - `caplog` contains start, per-parent, finish and (in a failing-engine variant) ERROR lines, each with the job id.

### Step 4: Web job tracking, TagSflButton, jobs tray (facts 11, 12, 13, 14, 15, 18)
- `web/src/lib/types.ts`: add `trace_url: string | null` and `started_at`/`finished_at` to `JobSnapshot`. Add those fields to `BackgroundJob.snapshot()` in step 3 if they are missing.
- `web/src/state/jobs.ts` (new): a store of tracked jobs keyed by id. `trackJob(snapshot)` starts `followEvents("/v1/corpus/jobs/{id}/events")` and updates `done/total/message/status`. On finish it invalidates the React Query keys `["chunk"]`, `["browse"]`, `["search"]` and `["facets"]`.
- `web/src/features/TagSflButton.tsx` (new): takes `scope` and `label`. While running it shows `n/N`, stage text and an elapsed `m:ss` timer. On failure it shows the error text. On success it shows a check mark briefly.
  - Replace `tagSfl` in `DetailPane.tsx`, the inline tag action in `factcheck/GateCard.tsx`/`FactCheckView.tsx`, and `RunsView.tsx:63`.
  - `FactCheckView` already follows events, so it moves onto the shared store.
- `web/src/features/JobsTray.tsx` (new): a Radix popover opened from `StatusFooter`. It lists active jobs first, then recent ones. Each row shows kind, label, progress, elapsed time, outcome and a "trace" link (`target=_blank`) when `trace_url` is set. The footer shows a count badge while any job is running.
- **Verify:** Vitest with a mocked `post` and `streamSse`:
  - clicking Tag SFL shows `0/1`, then `1/1`, then done;
  - the elapsed timer advances under fake timers;
  - a failed event shows the error on the button and in the tray;
  - completion invalidates the queries (spy on `queryClient.invalidateQueries`);
  - the tray renders a trace link.

### Step 5: Titles everywhere (facts 3, 4, 5)
- `web/src/lib/queries.ts`: `useNotebookTitles()` wraps `/v1/corpus/notebooks` with `staleTime` set to 5 minutes and returns `Map<id, title|null>`.
- `web/src/lib/utils.ts`: `notebookLabel(id, titles)` returns the title, or `shortId(id, 8)` followed by a muted "untitled" marker when there is no title. It never returns a full UUID. Document labels use the existing `title ?? document_id`, but the facet needs titles:
  - **backend:** `corpus_explorer.facets` returns `labels: {document: {id: title}}`, taken from the `title` already stored on chunk rows.
- Apply the labels in:
  - `FiltersPane.tsx`, Notebook and Document facets (title as the label, id in `title=` tooltip);
  - `RowMeta.tsx`;
  - `BrowseTable.tsx` "doc" cell, in plain font with no `shortId` truncation of titles (CSS ellipsis only);
  - `DetailPane.tsx` header (notebook › document);
  - `RunsView.tsx`;
  - `CommandPalette.tsx`;
  - `Breadcrumbs` (step 8).
- **Verify:**
  - Vitest renders each surface with a fixture UUID notebook that has a title and asserts the UUID string is absent from the text. An untitled fixture renders `untitled` plus an 8-character id.
  - grep check: no `shortId(` call is applied to a notebook id outside `notebookLabel`.

### Step 6: Browse table columns (facts 6, 7, 8, 9)
- `BrowseTable.tsx`:
  - `useReactTable({ columnResizeMode: "onChange", enableColumnResizing: true, state: { columnSizing, columnVisibility }, onColumnSizingChange, onColumnVisibilityChange })`.
  - Each header gets a 6px-wide resize handle on its right edge (`header.getResizeHandler()`; `onDoubleClick={() => header.column.resetSize()}`). The handle has `cursor: col-resize`, a hit area of at least 8px, and a `bg-primary/60` hover color with `transition-[background-color] duration-150`, matching the panel handles.
  - Row cells use `width: cell.column.getSize()`. The virtualized rows keep `ROW_H` and the text cell ellipsizes.
  - A "Columns" dropdown in the header (`@radix-ui/react-dropdown-menu`, already a dependency) holds a checkbox per column except select and text.
- `localStorage` keys `ce-browse-colsizing` and `ce-browse-colvis`. Every read and write is wrapped in try/catch, and the table falls back to the defaults.
- **Verify:**
  - Vitest fires pointer events on the handle and asserts the width style changes.
  - Re-mounting the table restores the width from storage.
  - A double-click restores the default `size`.
  - Toggling a column hides it, and the hidden state survives a re-mount.
  - Playwright drags the Document column handle 80px and asserts the bounding box grew.

### Step 7: Map zoom, pan, legend, explainer (facts 19–24)
- `MapView.tsx`:
  - Add a view transform `{k, x, y}` on top of the fit-to-bounds `scale`.
    - Wheel: zoom around the cursor (`k *= exp(-deltaY * 0.0015)`, clamped to 0.5–40).
    - Pointer drag: pan. A movement over 3px counts as a drag and suppresses the click.
    - "Reset view" button.
  - Hit-testing for hover and click uses the inverse transform.
  - Points of non-isolated groups draw at alpha 0.08.
  - Legend panel (top-right overlay, scrollable, max 12 entries plus "+N more"):
    - groups come from `colorBy` (topic, or document title from `/facets` labels or row titles);
    - each entry shows a color swatch, the title and a count;
    - clicking an entry toggles isolation, and clicking it again clears it.
  - The legend uses the same `colorFor(key)`, so the colors match the points.
  - Explainer line in the header, built from the response's method (add `method` to the `/map` response if it is not echoed):
    - "UMAP projection of chunk embeddings · 1 point = 1 chunk · color = topic · nearby points have similar meaning".
  - The tooltip adds the document title.
  - Clicking a point keeps calling `actions.open`.
- **Verify:**
  - Vitest (canvas mocked through `vitest-canvas-mock` or the existing setup) asserts the transform state after wheel and drag events, and Reset restores `{k:1,x:0,y:0}`.
  - The legend renders titles and counts from fixture points; clicking an entry sets the isolated key, and clicking again clears it.
  - The explainer text contains the method name and "1 point = 1 chunk".
  - A click after a drag does not open a chunk; a plain click does.
  - Playwright scrolls the wheel on the map and asserts that a point's projected position changes (exposed through a `data-k` attribute).

### Step 8: URL state, history, breadcrumbs (facts 25, 26, 27)
- `web/src/state/url.ts` (new):
  - `toUrl(state)` produces `/ui/<tab>?chunk=<id>&q=<submitted>&mode=…&nb=…&doc=…&kind=…` and the other non-empty filters (repeated params for lists).
  - `fromUrl(location)` returns a `Partial<AppState>`.
  - Replace `parseInitial` in `store.ts` with `fromUrl`.
- `store.ts`:
  - `setTab` and `open` call `history.pushState`.
  - Filter, query and mode changes call `replaceState`, so typing does not flood the history.
  - A `popstate` listener applies `fromUrl` under a `restoring` flag that suppresses re-pushing.
  - `reveal` and `startFactCheck` go through `setTab`, so they push as well.
- `web/src/features/Breadcrumbs.tsx` (new), placed under `Header`:
  - segments are `Tab › Notebook › Document › Chunk`, using `notebookLabel` and document titles;
  - a segment is shown only when known (from the open chunk's detail or from a single-valued filter);
  - clicking Notebook sets `filters={notebook_ids:[nb]}` and closes the chunk;
  - clicking Document sets `document_ids:[doc]` and closes the chunk;
  - clicking Tab closes the chunk and clears the narrowing filters.
- **Verify:**
  - Vitest round-trips `toUrl(fromUrl(x))` for representative states.
  - `setTab` grows `history.length`, and dispatching `popstate` restores the prior tab and chunk.
  - The Breadcrumbs component renders titles and its clicks dispatch the expected actions.
  - Playwright: Browse → open chunk → Map → Back shows Browse with the chunk open → Back shows Browse with no chunk → Forward. Reloading a deep URL restores the same view.

### Step 9: Polish pass, build, full verification (facts 29, 30, 31)
- better-ui check of every new control:
  - named `transition-property`, at most 150ms for color and opacity, `scale(0.96)` on press for buttons (Reset view, Columns, tray trigger);
  - concentric radii on the tray and legend surfaces;
  - shadow for elevation on the overlays;
  - icon stroke 1.5px beside regular text;
  - static cues for every animated state (the running button also shows its text).
- Rebuild the bundle: `cd web && pnpm build`. This writes into `src/notebooklm/server/static/ui`. Commit the old asset deletions and the new hashed assets together.
- Full checks: `cd web && pnpm typecheck && pnpm test && pnpm e2e`. Then:
  - `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`;
  - `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-report=term-missing --cov-fail-under=90`, checking the exit status directly.
- Manual: replay the 6 QA video steps against `notebooklm-server`. Record pass or fail per observation and the Langfuse trace URL of one SFL job in `verification.md`.

## Risks and open questions

- **Single-clause progress is coarse.** A one-chunk job still goes from 0/1 to 1/1 after about 30s, because `SFLEngine.forward` is a single blocking call. The stage text ("tagging clause 1/1"), the elapsed timer and the running state make the activity visible. Finer stages (ideational, then interpersonal pass) would need a callback inside `SFLEngine`. That is deferred unless the manual re-run still feels opaque.
- **Tracing depends on Langfuse keys.** When no tracer provider is installed, `job_span` yields `None`. `trace_url` is then null, the tray hides the link, and the logs still carry the job id. The tests install their own provider.
- **Title source at ingest.** If `client.notebooks.get` is unavailable or slow, ingest proceeds without a title. The next successful `/notebooks` list fills it in. Older notebooks stay "untitled" until a signed-in list call runs.
- **Map legend with document coloring** may have dozens of groups. The legend is capped at 12 entries plus "+N more" and a scroll area.
- **History volume:** filters use `replaceState` on purpose, so Back steps between tabs and opened chunks and not between every facet click. If you want facet changes in the history too, that is a one-line change.
- **Coverage gate:** the new backend code needs tests to keep coverage at or above 90%, using the full extras install from CLAUDE.md.
