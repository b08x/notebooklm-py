# Corpus Explorer — Plan

Shared understanding: [facts.md](facts.md) (63 facts). Visual reference: [mockups.html](mockups.html), direction **A · Workbench** and **A · Fact-check**.

## Solution approach

The explorer follows the existing layering: `_app/` business logic → transport adapter → UI.

- **`_app/`** gains the corpus operations (search, browse, detail, neighbors, delete, export, map, noise detection) and a transport-neutral **fact-check run controller**. All functions take an `AsyncSession` and return plain dicts, matching the convention in `_app/corpus.py`.
- **`server/routes/corpus.py`** and **`server/routes/factcheck.py`** expose them under `/v1/corpus/*`, behind the existing `require_auth` dependency (`server/app.py:478`). Run events reach the browser as SSE through `StreamingResponse(media_type="text/event-stream")`.
- **`web/`** is a Vite + React + TypeScript SPA (Tailwind v4, shadcn/ui, TanStack Query/Table/Virtual, cmdk, Motion). `vite build` writes to `src/notebooklm/server/static/ui/`, which the server mounts at `/ui` with an `index.html` fallback for client-side routes.
- The **TUI** keeps working and calls the new `_app` controller and the shared SFL formatter.

### Facts from the codebase that shape the plan

- `rrf_search` (`_app/clause_search.py:228`) is LLM-free and **does not** call `setup_dspy_router()`, so the server can call it directly. It is scoped by `document_ids` and returns only fused results, so it must be extended to return each leg's rank and a `vector_leg_ok` flag.
- `Embedding.clause_id` and `FactCheck.clause_external_id` are both `ON DELETE CASCADE` → deleting a `Clause` removes its embeddings and fact-checks. Parent, document and run deletes must delete the child clauses explicitly; whether `ParentChunk.run_id` cascades is checked in step 3.
- `removal_log` is shaped for notebook items (`notebook_id`, `item_id`, `item_type`, `action`, `reason`). Chunk deletes reuse it with `item_type ∈ {clause, parent, document, run}` and `action="delete_local"`. The `_app/curation.py` docstring says local clauses are "never purged". That policy changes here and the docstring is updated.
- Fact-checking has two gates:
  1. The clause `fact_check` job (`tui/jobs/handlers/fact_check.py`): a deterministic `checkworthiness.assess(sfl, tokens)` with no human in the loop; it requires `sfl_tag` to have run first.
  2. The audio assessment `run_full_assessment(..., hitl_callback=...)` (`_app/assessment.py:260`): the satire classifier with Y/N/S. Today the TUI implements this gate as a `time.sleep(0.1)` spin-wait on shared state (`tui/views/notebook_detail.py:257`).

  The new controller replaces that spin-wait and adds an optional human gate to the clause loop.
- `run_full_assessment` calls `setup_dspy_router()` (`assessment.py:273`). Under the project's DSPy rule this must run on the **main thread**. The server will call `setup_dspy_router()` once in its lifespan, and runs then bind `dspy.context(lm=dspy.settings.lm)`. The controller never calls `dspy.configure()`.
- The SFL bug: `_badges(interpersonal.get("tenor"))` (`tui/views/assessment_view.py:378`) iterates a **dict** and prints its keys.
- The topics table is empty → the map colors points by document. UMAP is available through `bertopic` (`assessment` extra); with no assessment extra, the map falls back to PCA with numpy.
- Corpus size today: 5,991 clauses, 703 parents, 88 documents, 88 runs, 0 topics.

## Ordered steps

### 1. Shared SFL formatter and TUI bug fix
- **New** `src/notebooklm/_app/sfl_format.py`: `format_sfl(sfl) -> {"ideational": {participants, processes, circumstances: [str]}, "interpersonal": {tenor, mood, modality: [str]}}`. It flattens nested dicts to `"key: value"` strings and passes through lists and strings.
- **Edit** `tui/views/assessment_view.py:366-380` to render from `format_sfl`.
- **Verify:** `uv run pytest tests/unit/test_sfl_format.py tests/unit/tui -q`. One new test renders `{"tenor": {"formality": "informal", …}}` and asserts that the value appears and the bare key list does not (fact-43).

### 2. Corpus query layer (`_app/corpus_explorer.py`)
- `search(session, query, mode, filters, top_k)`: keyword, vector or hybrid. This step refactors `clause_search.py` so the leg functions return their ranks, and the RRF result carries `kw_rank`, `vec_rank`, `score` and `vector_leg_ok`. Corpus-wide scope is used when there is no notebook filter.
- `browse(session, filters, cursor, limit)` with keyset pagination, and `facets(session, filters)` with per-value counts for notebook, document, run, strategy, fact-check status, length bucket and quality.
- `chunk_detail(session, external_id)`: the parent text with the char offsets of the child, ±2 neighbor sentences by `sentence_index`, entities from `tokens`/`groups`, `format_sfl(sfl)`, provenance, and the latest fact-check.
- `neighbors(session, external_id, k=10)`: pgvector `l2_distance` from the clause's stored embedding (no re-embedding). Each neighbor gets `near_duplicate = distance < NEAR_DUP_L2` (a constant, calibrated in tests on known duplicate pairs). `browse` gains a `has_near_duplicate` filter, computed as an `EXISTS` subquery with an HNSW/ivfflat index check (facts 19, 62).
- `runs(session)`, `stats(session)` (counts plus the max clause id for the "N new chunks" pill).
- **New** `_app/noise.py`: `classify_noise(text) -> "base64" | "numeric_table" | None`, using base64 charset/entropy plus run length, and digit/decimal token ratio. The flag is computed in SQL with matching regexes, so facets stay fast; a Python twin serves the unit tests.
- **Verify:** `uv run pytest tests/unit/app/test_corpus_explorer.py tests/unit/app/test_noise.py`. These run against the real Postgres on :5435, seed a throwaway run and **fail** if the DB is unreachable (facts 10–20).

### 3. Delete and export (`_app/corpus_mutations.py`)
- `delete(session, level, ids, reason) -> DeleteReceipt` for levels clause, parent, document and run. One transaction deletes the clauses (embeddings and fact_checks go with them by cascade), then the parents, then the runs as needed, and writes one `RemovalLog` row per action.
- **Confirm before delete (fact-23):** `POST /corpus/delete/preview` returns the counts per table (clauses, embeddings, fact_checks, parents, runs) without deleting anything. The UI shows them in a confirm dialog, and only Confirm calls `POST /corpus/delete`. Cancel sends nothing.
- `export(session, ids, fmt)` → Markdown/JSON string; `export_to_note(client, session, ids)` → `client.notes.create(notebook_id, …)` per source notebook.
- Check `ParentChunk.run_id` / `Clause.parent_id` `ondelete`. If they don't cascade, delete explicitly in the order above. No schema migration.
- **Verify:** DB tests assert that row counts drop across `clauses`, `embeddings` and `fact_checks`, and that exactly one `removal_log` row exists per action (facts 21–22, 25).

### 4. RAG answer (`_app/corpus_answer.py`)
- `answer_notebooklm(client, session, question, hits)`: takes the hits from `search`, builds a prompt with `[C1]…[Cn]` excerpts, groups the hits by notebook, and calls `client.chat.ask(nb_id, prompt, source_ids=<document_ids of hits>)`. It returns the answer text plus a `{Cn: external_id}` citation map.
- `answer_litellm(model, question, hits)`: an async generator over `litellm.acompletion(..., stream=True)`. It doesn't call `dspy.configure`, so it is safe under the server.
- **Cross-notebook DSPy pipeline (fact-60)** in `_app/corpus_agent.py`. When the hits span more than one notebook:
  - A `dspy.ReAct(CorpusAnswer, tools=[search_corpus, chunk_detail, neighbors, ask_notebook])` agent runs once per notebook. `ask_notebook` wraps `answer_notebooklm` for one notebook.
  - `dspy.MultiChainComparison(CorpusAnswer, M=len(notebooks))` merges the per-notebook completions into one answer with `[Cn]` citations.
  - Each tool is a plain async function bridged into the agent thread with `asyncio.run_coroutine_threadsafe`.
  - The whole pipeline runs in `asyncio.to_thread` under `with dspy.context(lm=dspy.settings.lm)` (fact-63).
- **Deep mode (fact-61):** `dspy.RLM` (available in the installed dspy 3.3.1) explores the full hit set through its sandboxed REPL. It is labeled experimental. If the sandbox (Deno/Pyodide) is missing, it returns a typed `deep_mode_unavailable` error that the UI shows as a banner.
- Ask modes in the UI: **NotebookLM** (single notebook), **Corpus agent** (DSPy, chosen automatically when the hits span notebooks), **Deep (experimental)**, and **Model…** (litellm freeform).
- **Verify:** unit tests with a fake client assert the scoped `source_ids` and the citation map; a litellm stream test monkeypatches `acompletion` (facts 27–29).

### 5. Fact-check run controller (`_app/factcheck_runs.py`)
- `FactCheckRun` holds the queue items, their statuses, counts, a ring buffer of events with a monotonically increasing `seq`, and `auto_skip`. Its API:
  - `start()` and `subscribe(after_seq)` (async iterator)
  - `decide(item_id, check: bool)`, `set_auto_skip(bool)`, `pause()`/`cancel()`.
- **Gate source (facts 58–59):** `gate_source = "jev" | "rule"`.
  - **Jev** calls the existing `_preprocessing/jev.py` `JevClient` with a `ChoiceQuestion` (`checkworthy` / `meta_dialogue_or_satire` / `filler`, criteria derived from the TUI satire classifier prompt) and the clause text, SFL and ±2 neighbor lines as `state`. Its `probabilities` feed the gate card.
  - **Rule** keeps `checkworthiness.assess`.
  - A `JevError` falls back to the rule gate for that item and emits a `gate_fallback` event.
  - **New** `scripts/compare_gates.py` samples N stored chunks, runs both gates, and prints agreement and a confusion matrix.
- **Gate:** `await self._gate(item, reason, probability)` emits a `gate` event and awaits an `asyncio.Future` that `decide()` resolves; auto-skip resolves it immediately. For the audio path, `sync_gate()` wraps it with `asyncio.run_coroutine_threadsafe` so `hitl_callback`, which runs in a worker thread, can block on it.
- **Move** the loop body of `tui/jobs/handlers/fact_check.py:run_fact_check` into the controller (`gate_mode="auto"|"interactive"`). The TUI handler becomes a thin adapter that keeps the current `JobContext` behavior.
- **Replace** the spin-wait in `tui/views/notebook_detail.py:257-282` with `FactCheckRun.sync_gate`; the TUI y/n/s keys call `decide` and `set_auto_skip` (fact-40).
- A `RunRegistry` in server app state keeps runs alive independent of SSE connections (fact-39).
- **Verify:** the async unit tests:
  - the gate pauses until `decide`
  - auto-skip resolves without waiting
  - `subscribe(after_seq)` replays the missed events
  - the TUI keypress tests stay green
  - the guardrail `tests/_guardrails/test_app_boundary.py` passes, so nothing in `_app` imports `tui`.

### 5b. General assessment: any document, plus artifact ingest
- **Scope:** add `Scope = notebook | document_ids | run_ids | external_ids` to `sfl_tag` (`tui/jobs/handlers/sfl_tag.py:41-59`, which today filters only on `ChunkRun.notebook_id`) and to `fact_checks.load_children`. The TUI keeps passing the notebook scope. The web passes document, run or selection scopes (facts 49–50).
- **New** `_app/artifact_ingest.py`:
  - `list_ingestible(client, notebook_id)`: returns the artifacts with `kind` and either `ingestible: bool` or a disabled `reason` (infographic and slide deck → "image-only, not ingestible").
  - `artifact_to_text(client, notebook_id, artifact)`:
    - audio/video → `download_*` into a temp dir → **`prepare_audio()`** → the chosen adapter in `asyncio.to_thread` → speaker-labelled lines ("[Speaker 0] …"), matching the format the assessment already produces → the temp FLAC is deleted in `finally`. The downloaded original is never modified.
  - **New** `_preprocessing/audio_prep.py`, ported from `audio-segment-extractor/src/audioseg/preprocess.py` (fact-52):
    - mono, original sample rate, `PCM_16` (or `PCM_24` for sources 24-bit and wider)
    - 80 Hz high-pass (scipy)
    - −19 LUFS with peaks capped at −1 dBFS (pyloudnorm)
    - lossless FLAC (soundfile).

    It adds `pyloudnorm` and `soundfile` to the `assessment` extra; both are missing today.
  - **Adapter choice per request (fact-57):** `TranscriptionOptions(provider, diarize, language|None)` replaces the env-only `_build_transcription_adapter()`. The defaults come from the `.env`/config keys `NOTEBOOKLM_TRANSCRIBE_PROVIDER` (falling back to the existing `NOTEBOOKLM_ASSESSMENT_TRANSCRIBE_PROVIDER`), `NOTEBOOKLM_TRANSCRIBE_DIARIZE` (default `true`) and `NOTEBOOKLM_TRANSCRIBE_LANGUAGE` (default `auto`). They are documented in `docs/configuration.md` and returned by the providers endpoint as `defaults`. `GET /corpus/transcription/providers` returns `[{id, env_var, key_present}]` for speechmatics, assemblyai, deepgram and transcribe_cpp.
    - report → markdown
    - quiz/flashcards → Q/A lines
    - mind map → indented outline
    - data table → rows.
  - `ingest_artifact(...)` → `IngestionService.ingest_text(document_id=artifact.id, notebook_id, …)` with `params={"kind": <kind>, "artifact_id": …, "title": …}` stored in `chunk_runs.params`, so no schema migration is needed.
  - **Checksum gate (fact-56):** hash the downloaded bytes, or the artifact text for text kinds, *before* transcription and compare it with the active run's `source_hash` for that `document_id`. If they match → return `skipped_unchanged` (no transcription cost). Only a different hash, or `force=true` ("Force re-ingest"), creates a new run, which becomes active and deactivates the old one.
  - **Converter registry (fact-54):** `CONVERTERS: dict[kind, Converter]`. Infographic and slide deck have no converter and report "image-only, not ingestible yet". A multimodal embedder (image, audio or video vectors) can be registered later without changing `ingest_artifact`'s callers.
- **Document kind:** `params->>'kind'`, defaulting to `source`; notes are flagged where the existing ingest path knows about them. It is exposed in facets and in browse rows (fact-55).
- **HTTP:**

  | Method | Path |
  |---|---|
  | GET | `/corpus/artifacts?notebook_id=` |
  | POST | `/corpus/artifacts/{id}/ingest` (a background run reported through the same run-event SSE) |
  | POST | `/corpus/sfl/runs` with a scope |

- **Verify:**
  - Unit tests per artifact kind with a fake client and a fake transcription adapter: the text shape and the speaker labels are kept.
  - DB tests: ingesting unchanged content returns `skipped_unchanged` and makes no transcription call; a changed hash or `force` leaves exactly one active run.
  - A scope test shows that `sfl_tag`/`load_children` with `document_ids` touch only those documents (facts 49–56).

### 6. HTTP adapter
- **New** `server/routes/corpus.py`:

  | Method | Path |
  |---|---|
  | GET | `/corpus/stats` |
  | GET | `/corpus/facets` |
  | GET | `/corpus/chunks` |
  | GET | `/corpus/chunks/{id}` |
  | GET | `/corpus/chunks/{id}/neighbors` |
  | POST | `/corpus/search` |
  | POST | `/corpus/delete` |
  | POST | `/corpus/export` |
  | POST | `/corpus/export/note` |
  | POST | `/corpus/answer` (SSE when `model` is set) |
  | GET | `/corpus/map` |
  | GET | `/corpus/runs` |
  | GET | `/corpus/health` (pg, embedder, jobs) |

- **New** `server/routes/factcheck.py`:

  | Method | Path |
  |---|---|
  | POST | `/corpus/factcheck/runs` |
  | GET | `/corpus/factcheck/runs/{id}` |
  | GET | `/corpus/factcheck/runs/{id}/events?after=` (SSE) |
  | POST | `/corpus/factcheck/runs/{id}/decision` |
  | POST | `/corpus/factcheck/runs/{id}/auto-skip` |

- A DB session dependency comes from `async_session_maker`. A SQLAlchemy `OperationalError` or `OSError` on connect → **503** `{"error":"database_unreachable"}` (fact-4).
- The map endpoint caches its projection keyed by `(clause_count, max_clause_id)`.
- `server/app.py` changes:
  - include both routers in `v1`
  - mount `StaticFiles(directory=static/ui, html=True)` at `/ui`, public like `/healthz` so the SPA shell can load
  - add `setup_dspy_router()` to the lifespan (main thread)
  - allow `text/event-stream` responses through the body-limit middleware.
- **Verify:** `tests/server/test_corpus_routes.py` and `tests/server/test_factcheck_routes.py`:
  - 401 without a token on every route (fact-2)
  - 503 with a bad `DATABASE_URL` (fact-4)
  - the happy paths against the real Postgres
  - SSE replay by `after`
  - `GET /ui` returns the SPA (fact-1).

### 7. Web app scaffold (`web/`)
- Install: `pnpm create vite web --template react-ts`, then Tailwind v4 (`@tailwindcss/vite`), shadcn/ui init, `@tanstack/react-query`, `@tanstack/react-table`, `@tanstack/react-virtual`, `cmdk`, `motion`, `lucide-react`, `sonner` (status toasts), and Vitest with Testing Library.
- Theme tokens on `:root` copy `tui/theme.py` COLORS (dark default) plus a light set. Theme switching suppresses transitions (inject `*{transition:none!important}`, force a reflow, remove on the next frame) (fact-8).
- An API client with a bearer token from a first-run token prompt, kept in `localStorage` (fact-3). A Vite dev proxy sends `/v1` → `127.0.0.1:<server port>`.
- `outDir: ../src/notebooklm/server/static/ui`, `base: "/ui/"`.
- **Verify:** `pnpm -C web build` emits `index.html`, and the server serves it at `/ui` (fact-5).

### 8. Workbench shell and Search / Browse / Detail
- **Shell:**
  - a header with the tabs (Search · Browse · Map · Runs · Fact-check) and the mode toggle
  - three resizable panes (filters | results | detail)
  - a footer polling `/corpus/health` (fact-9)
  - the "database unreachable" blocking screen.
- **Search:** results list with kw/vec/rrf bars and `<mark>` highlighting of query terms; a "vector leg unavailable" banner.
- **Browse:** a TanStack Table with Virtual rows (keyset pages via `useInfiniteQuery`), the facet sidebar with counts, the quality filter and noise tags.
- **Detail:** tabs for Context (parent with the child highlighted, neighbors), Linguistics (entities and SFL chips from the formatter), Similar items (neighbors with distance and near-duplicate badges) and Raw.
- **Live updates:** `refetchInterval: 5000` on stats → an "↑ N new chunks" pill (fact-33).
- **Verify:** Vitest specs for the result row (score bars, highlight), the detail pane (child highlighted), the facet counts and the new-chunks pill.

### 9. Selection, delete, export, Ask
- Selection: checkbox, `x` and shift-click range; a bulk bar with Delete, Export and Re-fact-check.
- Delete: a shadcn `AlertDialog` showing the preview counts, with Cancel and a destructive Confirm; delete menus for the four levels in the detail pane.
- Artifact ingest dialog (fact-57), modeled on the audio-segment-extractor panel: a provider radio group, a key status line, a Diarize switch, a Language select (Auto-detect) and a Transcribe button. Non-audio kinds skip straight to Ingest.
- Export: Markdown/JSON download (Blob) and "Push as note".
- Ask: a drawer with a NotebookLM default and a freeform model combobox. The litellm path streams over SSE (`fetch` + `ReadableStream`); NotebookLM shows a progress state. `[Cn]` chips open the cited chunk.
- **Verify:** Vitest tests:
  - the confirm dialog: Cancel → no delete request; Confirm → exactly one request
  - citation click → the detail pane opens
  - the ingest dialog shows key-missing for a provider without an env var.

### 10. Map and Runs
- **Map:** a canvas scatter (`regl-scatterplot`, or plain Canvas2D for about 6k points) with color by document, hover tooltip and click → detail.
- **Runs:** a chunk_runs table with the active flag, and an ingest progress row while a job runs.
- **Verify:** an endpoint test for the map shape (x, y, document_id, external_id) and a manual visual check.

### 11. Fact-check screen
- **Left:** queue with status icons and the counts/elapsed header.
- **Center:**
  - the gate card (probability; Skip `Y`, Fact-check `N`, Auto-skip toggle `S`)
  - transcript context (±2 lines)
  - SIFT step cards.
- **Right:** the evidence log (verdict, confidence, rationale, Langfuse link built from `trace_id` plus `LANGFUSE_HOST`) and the SFL tab.
- An `EventSource`-style reader resumes from the last `seq` on reconnect.
- "Run sfl_tag first" errors show as an actionable banner.
- **Verify:** Vitest for the gate (pressing `n` posts the decision; the auto-skip toggle posts and hides the gate).

### 12. Command palette, shortcuts, polish
- `cmdk` palette actions: switch tab, focus search, delete selection, start fact-check run, toggle theme.
- Shortcuts: `/ j k x Enter Backspace ?`, plus a `?` cheat sheet.
- better-ui rules:
  - press `scale(0.96)`
  - explicit `transition-property` (no `transition: all`)
  - concentric radii
  - icon cross-fade values from the better-ui skill (scale 0.25→1, opacity 0→1, blur 4px→0)
  - `AnimatePresence initial={false}`.
- **Verify:**
  - Vitest palette test.
  - `grep -rn "transition: all\|transition-all" web/src` returns nothing (fact-44).
  - `/better-ui` review pass reports `Approve`.

### 13. End-to-end and gates
- `web/e2e/smoke.spec.ts` (Playwright): start `notebooklm-server` with a test token against Postgres seeded with a fixture run → search → open chunk → delete → Cancel (the row is still present) → delete → Confirm → the row is gone (fact-47).
- **Final gate:**
  - `uv run ruff check . && uv run ruff format --check .`
  - `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`
  - `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` (exit status checked directly)
  - `pnpm -C web test`
  - `pnpm -C web build`
  - `pnpm -C web exec playwright test`.

## Risks and open questions

- **Jev is an alpha API** (`/api/alpha/decisions`, OpenRouter). Each gated chunk is one paid call: about 300 per notebook run. The rule gate is the fallback and is selectable. `compare_gates.py` measures the disagreement between the two before you choose Jev as the default.
- **SFL prerequisite.** Clause fact-check runs fail unless `sfl_tag` has run. How many of the 5,991 clauses have `sfl` set is unverified. The UI should offer "Tag SFL first", which only enqueues the existing job.
- **Hard delete with confirmation.** This replaces the undo toast. The "never purged" line in the `_app/curation.py` docstring is updated to name the explorer's confirmed delete as the one exception.
- **Delete during ingestion.** Deleting a document while ingestion is writing to it can race. The server refuses document/run deletes for runs whose ingest job is still running (409).
- **Coverage gate.** A large number of new `_app` and route lines must keep total coverage ≥ 90%, so the route and DB tests are required, not optional.
- **Static assets in the wheel.** The built `static/ui` is generated output; it is committed or built on demand (personal fork, so committing the build is acceptable).
- **Transcription cost and time.** Audio and video ingest runs Deepgram (paid) or a slow local `transcribe_cpp`. The ingest dialog shows which provider will run. The existing `*_diarization.json` cache in `artifacts_dir` is reused, so the same artifact is never transcribed twice.
- **Document kind for older runs.** Runs ingested before this change have no `params.kind` and show as `source`. Notes can't be told apart from sources retroactively unless the ingest path already recorded it.
- **Out of scope, noted for later:** deduplicating near-duplicate chunks and filtering hallucinations across the corpus (you plan to design those filters separately), and multimodal embedding of images, audio and video.
- **NotebookLM answer scoping.** `chat.ask` covers one notebook per call. Cross-notebook questions go through the DSPy corpus pipeline instead (step 4).
- **`dspy.RLM` sandbox.** RLM needs its interpreter sandbox. If it isn't installed, Deep mode stays visible but reports itself unavailable; nothing else depends on it.
- **Audio preview and clip export are not in this goal.** The FLAC spec says preview and clip export use the original audio; that rule is honored by never touching the original, but the explorer adds no audio player.
- **The corpus will be wiped after this phase.** No migration or backfill is needed for older runs (no `params.kind`).
