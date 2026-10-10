# Plan: TUI job queue, Ingest/Fact-check workbench, parent/child chunking

Facts: [facts.md](facts.md) (40 accepted). Decisions: [grill-notes.md](grill-notes.md).
Fact numbers below refer to `facts.meta.json` ids (`fact-N`).

## Solution approach

The plan has three layers, built in dependency order.

1. **Job layer.** A Redis-backed job store (`nblm:` prefix) plus an in-process worker pool. It replaces the single-future slots `background_task` and `compiler_task`. Every long-running action becomes a job of some kind, and every job opens one root OpenTelemetry span.
2. **Data layer.** One Alembic migration:
   - truncates the legacy flat clauses
   - adds `chunk_runs`, `parent_chunks`, `fact_checks`, `topic_runs` and `topics`
   - adds `run_id`, `parent_id`, `sfl` and `topic_id` columns to `clauses`
   
   A strategy interface (`chunk(text) -> list[ParentChunk]`) is shared by three chunkers: recursive, cluster-semantic and dynamic-window. `IngestionService` writes one run per call.
3. **UI layer.** A mode bar, with each mode building its own layout. Jobs, Ingest and Fact-check are new mode renderers that read only from Redis and Postgres.

The database is a disposable test DB, so the plan has no backups and no confirmation prompts.

**Every process starts manually.** Only a key press in the TUI, or the one-off script in step 13, enqueues a job. No job handler enqueues another job. The order ingest → sfl_tag → fact_check, and ingest → topic_model, is enforced by checking prerequisites when a job starts, not by chaining jobs.

## Ordered steps

### 1. Dependencies and tracing helper
- `pyproject.toml`:
  - Add `redis>=5` to the `assessment` extra, which the TUI already requires.
  - Add a new `topics` extra with `bertopic`, `umap-learn` and `hdbscan`.
  - Run `uv lock` and `uv sync` with every extra in the canonical install plus `topics`.
- New `src/notebooklm/_app/tracing.py`. `job_span(kind, **attrs)` is a context manager that opens the root span `job.<kind>` with the tracer `_app/assessment.py:102` already configures, and yields a hex `trace_id`. `trace_url(trace_id)` builds the address from `LANGFUSE_HOST`, default `http://tinybot:3000`.
- **Verify:** `uv run python -c "import redis, bertopic"`. A unit test checks that `job_span` yields a 32-hex trace id when an in-memory span exporter is installed.

### 2. Schema migration (facts 18, 20, 25, 29, 30, 36)
New revision `f2c1…` after `e7a4c1f9b3d2`:
- `TRUNCATE clauses, embeddings CASCADE` (fact 25).
- `chunk_runs`: id, document_id, notebook_id, strategy, params JSONB, chunker_version, source_hash, trace_id, n_parents, n_children, mean_len, p95_len, entity_vetoes, created_at, is_active.
- `parent_chunks`: id, run_id FK, document_id, index, text, char_start, char_end.
- `clauses`:
  - New columns: `run_id` FK, `parent_id` FK to parent_chunks (cascade), `sfl` JSONB, `topic_id` nullable.
  - The `tokens` and `groups` columns already exist and will be filled.
  - `external_id` changes to `{document_id}:{run_id}:{index}`, so several runs of one document can exist at once. That is what `x` compare needs.
- `fact_checks`: id, clause_external_id FK, run_id, verdict enum (`supported`, `contradicted`, `unverifiable`, `skipped_no_framework`, `not_checkworthy`), confidence float, probabilities JSONB, sift_steps JSONB, citations JSONB, trace_id, model, latency_ms, created_at.
- `topic_runs` and `topics`: id, run_id, label, keywords JSONB, size.
- Update `db/models.py` to match.
- **Verify:** `uv run alembic upgrade head` against localhost:5435, then `psql … -c "\d clauses"`. A unit test in `tests/unit/db/` builds the ORM metadata and asserts the new columns and foreign keys exist.

### 3. Job store and runner (facts 2–10, 34, 39)
New package `src/notebooklm/tui/jobs/`:
- `store.py` (`JobStore`):
  - `enqueue(kind, notebook_id, payload)` does HSET `nblm:job:<id>` plus ZADD on `nblm:jobs:queued` and `nblm:jobs:all`.
  - `claim()` uses ZPOPMIN.
  - Also: `update(id, **fields)`, `add_item` / `update_item` (a hash per item, with its id kept in the list `nblm:job:<id>:items`), `cancel`, `retry`, `clear_finished`, `list_jobs(kind, status)`.
  - `mark_interrupted_on_startup()` scans only `nblm:jobs:all`.
  - Finishing a job calls EXPIRE with 7 days on the job and item keys (fact 9).
  - The key prefix is a constructor argument, so tests pass `nblm:test:<uuid>:`.
- `runner.py` (`JobRunner`):
  - `NOTEBOOKLM_TUI_JOB_WORKERS` threads (default 2). Each thread loops: claim, then run the handler under `asyncio.run` inside `job_span`, then write the status.
  - Cancel is cooperative: handlers call `ctx.check_cancelled()` between items.
  - The handler context exposes `ctx.consume_token()`, which wraps `TUIState.consume_token` behind a new `threading.Lock`. `TUIState` is currently not thread-safe (fact 4).
  - DSPy LM binding: the runner reads `dspy.settings.lm` on the main thread when the TUI starts, and each worker wraps handlers in `dspy.context(lm=lm)`. That is the CLAUDE.md hard rule (fact 22).
- `kinds.py`: a registry of `kind -> handler` covering download, ingest, sfl_tag, fact_check, compile, generate and topic_model (fact 10).
- `app.py`:
  - At startup, PING Redis. If that fails, print `Redis unreachable at <url>: <error>. Start Redis and retry.` to stderr and exit with status 2 before the Live screen opens (fact 39).
  - Build the store and runner at startup and call `mark_interrupted_on_startup()`.
  - Remove the polling of `background_task` and `compiler_task`.
  - Redraw while any job is running, reading the job list at most every 250 ms.
- **Verify:** `tests/unit/tui/jobs/test_store.py` and `test_runner.py` run against the live local Redis under a unique prefix and delete only their own prefix. A session-scoped fixture pings `NOTEBOOKLM_REDIS_URL` (default `redis://localhost:6379/0`) and calls `pytest.fail`, never `skip`, naming the URL when Redis is unreachable (fact 39). They cover:
  - enqueue, claim and update fields
  - startup marks running jobs interrupted
  - cancelling a queued job removes it; cancelling a running job stops it at the next check
  - retry re-queues
  - TTL is set on finish
  - two workers never run more than two jobs at once (a barrier-based test)
  
  Fact 3: a test wraps the redis client, records every key argument, and asserts that each one starts with the prefix.

### 4. Download as a job (facts 1, 6, 7)
- Split `_download_assets_async` (`views/notebook_detail.py:113`) into a handler with the signature `(ctx, notebook_id)`. Each source or artifact becomes one item: skipped if already in `LocalAsset`, done, or failed with the error text. The single `download_progress` dict goes away.
- `start_download` becomes `store.enqueue("download", nb_id)` and returns immediately.
- **Verify:** unit tests with a fake client:
  - enqueueing three notebooks gives three jobs
  - an artifact that raises appears as a failed item with its message
  - a second run skips the `LocalAsset` rows the first run created (fake DB session)

### 5. Mode bar and per-mode layouts (facts 11–15)
- Add a `Mode` enum (`NOTEBOOKS`, `INGEST`, `FACT_CHECK`, `COMPILER`, `JOBS`, `LOGS`) to `TUIState`. Existing `View` values map to a mode: chat, detail and list map to `NOTEBOOKS`; assessment views map to `FACT_CHECK`.
- `layout.py`: `build_layout(mode)` returns a layout per mode with the slots `header`, `modebar` (size 3), the body panes, and `footer`.
- `app.update_layout` rebuilds the layout when the mode changes.
- `renderers/modebar.py` renders `1 Notebooks │ 2 Ingest │ …`, highlights the active mode, and shows `Jobs (n▸)` using the count of running jobs.
- `keypress.py`:
  - Keys `1`–`6` set the mode.
  - The existing `p`, `A`, `L` and `n` keep working (fact 13).
  - `c` and Tab open chat only from the Notebooks mode (fact 14).
  - The number keys must not fire inside text-entry submodes (chat input, context editor). Those submodes return earlier in `handle_key`, so placing the mode-key branch after them is enough.
- `renderers/jobs.py`: the Jobs mode uses the full width. Left: the job list with kind, notebook, status, a percent bar and filter chips. Right: phase, the item list, and the trace link. Keys: `x` cancel, `R` retry, `C` clear, `f` cycle filter (fact 8).
- **Verify:** extend `tests/unit/tui/test_keypress_navigation.py` (number keys, letter keys, no mode switch while editing) and `test_layout.py` (each mode has a `modebar`; the Jobs layout has no `sidebar`). A renderer test captures the mode bar text with a running job count of 2.

### 6. Chunkers (facts 16, 17, 21, 22)
Rewrite `_preprocessing/chunkers.py` as a package `_preprocessing/chunking/`:
- `base.py`: `ChildChunk(text, char_start, char_end)`, `ParentChunk(text, children, char_start, char_end)`, `ChunkStrategy` protocol (`name`, `version`, `params`, `chunk(text) -> list[ParentChunk]`), and `ChunkStats` (holds `entity_vetoes`).
- `recursive.py` (`RecursiveSplitter`):
  - The separator ladder: `\n\n` → `\n` → `(?<=[.?!])\s+` → spaCy `doc.sents` → whitespace. Each level applies only to pieces still over `max_chars`.
  - Parents come from levels 1–2 with `parent_max_chars` (default 4000). Children come from the ladder within each parent with `child_max_chars` (default 512).
  - `EntityGuard` runs spaCy NER once per parent and drops any candidate split offset inside an entity span, unless the entity alone exceeds the limit. Each veto is counted.
- `semantic.py` (`ClusterSemanticChunker`):
  - Atomic sentences come from `RecursiveSplitter` at sentence level, then are embedded with the existing `OllamaEmbedder`.
  - Cosine distances between adjacent sentences determine the breaks: a break goes where the distance exceeds `np.percentile(d, 90)`, with min/max child-size merging.
  - It returns the sentence vectors so ingest can reuse them for the children, instead of embedding twice.
  - Parents are the recursive parents.
- `dynamic.py` (`DynamicWindowChunker`): a DSPy `ChainOfThought` signature `(sentences: list[str], target_range) -> boundaries: list[int]`. It validates the output: indices sorted and in range. If the output is invalid, it falls back to the recursive child split and records `fallback=true` in the run parameters.
- `__init__.py` holds a `STRATEGIES` registry. Keep `StructuralCoherenceChunker` importable as an alias until callers are migrated, then delete it.
- **Verify:** `tests/unit/preprocessing/test_chunking.py`:
  - a fixture text where each ladder level is needed shows each level is reached only when a piece is oversized
  - a split candidate inside "New York Times" is vetoed
  - an oversize entity still splits
  - semantic: the break lands where a synthetic embedding sequence jumps
  - dynamic: a stubbed LM returns bounds; invalid bounds trigger the fallback
  - a test asserts `dspy.configure` is not called from a worker thread

### 7. Ingestion rewrite (facts 18–20, 23, 24)
- `IngestionService.ingest_text(..., strategy)`:
  - Hash the source text, then create a `chunk_runs` row with `trace_id` taken from the current span.
  - Chunk the text and write the `parent_chunks` rows.
  - Run spaCy over the children with `nlp.pipe` and store `tokens` (text, lemma, pos, tag, dep, head, morph as a dict) and `groups` (noun chunks plus clause groups by root subtree, reusing `sfl_engine` pass-1 logic).
  - Embed the children only, unless the strategy already returned vectors.
  - Write the children with `run_id` and `parent_id`, compute aggregate counts, and set `is_active` on the new run, clearing it on older runs of the same document.
- Deletion is scoped to `(document_id, run_id)` and no longer to `document_id` alone.
- The transcript path `_app/assessment.py:431` (`ingest_chunks`) goes through the same run-creation code. Each transcript turn becomes a parent, with sentence children (fact 24).
- An `ingest` job handler wraps `_ingest_notebook_async`, creating one item per source or note and passing `strategy` from the payload.
- **Verify:** an integration-style unit test with a fake embedder and the real spaCy model ingests a two-paragraph text and asserts:
  - parent and child counts
  - every child has a `parent_id`
  - embedding rows exist only for children
  - `tokens[0]` has all seven keys
  - `chunk_runs` aggregates are correct
  - re-running with another strategy keeps both runs and flips `is_active`

### 8. Ingest mode (facts 26–28, 38)
- New `views/ingest_view.py` and `renderers/ingest.py`, following the Tree Ring Memory layout:
  - Left: a document tree. Each document expands to its parents, showing child count and a bar, for the active run.
  - Top right: the children of the selected parent.
  - Bottom right: a detail pane that toggles between `t` tokens, `d` deps (flat table: token, POS, dep, → head, morph), `g` groups, and `s` SFL (mood/modality/tenor or "not tagged"). Once a topic run exists, the topic label shows here too.
- Keys:
  - `i` queues an ingest job for the selected notebook.
  - `r` opens a strategy picker (recursive, cluster-semantic, dynamic-window) and queues ingest with that strategy.
  - `x` picks two runs and shows their `chunk_runs` counts side by side.
  - `s` queues `sfl_tag`; `T` queues `topic_model`.
- Data comes from a small read API in `_app/corpus.py` (async SQLAlchemy queries), cached per selection.
- **Verify:** renderer tests with fixture rows check that the deps table header and columns appear and that the toggle switches panes. `x` is checked with two fixture runs. Then run the TUI manually with the `run` skill and take a screenshot of the Ingest mode against real data.

### 9. SFL tag job (fact 29)
- `sfl_tag` handler: load the active-run children of a notebook and run `SFLEngine` on each one in a worker under `dspy.context`. Write `clauses.sfl = {mood, modality, tenor, pass1}`. There is one item per parent so progress stays readable.
- **Verify:** a unit test with a stubbed `SFLEngine.forward` checks that every child's `sfl` is set and that the stub ran under a bound LM context.

### 10. Fact-check rewrite (facts 30–33, 35)
The checker is split into two stages: an LLM gathers evidence, and a decision model (Jev) gives the verdict.
- **Prompt overhaul, evidence stage.** The `sift.skill` SKILL.md is no longer used as one prose prompt. A typed DSPy module runs one signature per SIFT step:
  - `StopSignature` decomposes the claim into the specific checkable assertion and its type (causal, numeric, attribution, temporal).
  - `InvestigateSourceSignature` reports who the cited or implied source is and how reliable it is.
  - `FindCoverageSignature` writes search queries and summarizes what other sources say, using the existing web search tool (Exa).
  - `TraceClaimSignature` identifies the original source of the claim and whether it was quoted accurately.
  
  The module returns `sift_steps` (four structured fields) and `citations` (url, title, quote). This stage does not output a verdict. `sift.skill` stays the reference document; its method is written into the signature docstrings and field descriptions.
- **Verdict stage, Jev.** POST to `https://openrouter.ai/api/alpha/decisions` with `model: typesafe/jev-1.13`:
  - `state`: `{claim, parent_context, sift_steps, citations}`
  - `questions.verdict`: `type: choice` with criteria for `supported` (every factual element is backed by a cited source), `contradicted` (at least one cited source directly contradicts it) and `unverifiable` (the evidence neither backs nor contradicts it).
  - The response's `choice`, `confidence` and per-label `probabilities` are stored. `fact_checks` gains `confidence` and `probabilities` JSONB columns (add these in the step 2 migration).
  - Implementation: `_preprocessing/jev.py` (`JevClient`, httpx, `OPENROUTER_API_KEY`, retry on 429/5xx). The DSPy instrumentor doesn't capture this call, so `JevClient` opens a child span `jev.decision` with the request state and response in its attributes.
  - Cost: $0.042 per million input tokens and nothing for output, so the verdict call costs far less than the evidence stage.
- `FactCheckAdapter.check` returns `{verdict, confidence, probabilities, sift_steps, citations}`. When the framework is missing, the verdict is `skipped_no_framework`, and neither stage runs.
- **Order: fact-checking runs only after SFL tagging** (your feedback on the plan). The `fact_check` job for a notebook or parent reads `clauses.sfl`. If any child in scope has no SFL output, the job stops before calling any LLM, sets status `failed` with the error "run sfl_tag first (N children untagged)", and writes no rows. The job never queues `sfl_tag` itself.
- `_preprocessing/checkworthiness.py`, the gate, reads only the stored SFL output:
  - It passes children with declarative mood and modality ≥ medium.
  - Hedge cues in the spaCy tokens (`might`, `may`, `perhaps`, `could`) reject the child.
  - It never calls an LLM.
  - A rejected child gets a `fact_checks` row with verdict `not_checkworthy`.
- This replaces the "spaCy fallback when SFL is missing" part of fact 32; facts.md has been updated to match.
- `run_fact_check_for_chunk` appends a `fact_checks` row with `trace_id` from the span, the model, and `latency_ms`. It sets `Clause.fact_check_passed` only for `supported`/`contradicted`, and leaves it NULL otherwise (fact 31).
- `fact_check` handler: scoped to a notebook or a parent; one item per child.
- Fact-check mode (`renderers/factcheck.py`) replaces the assessment layout:
  - Left: the claims list with verdict glyph, latency and SFL mood/modality columns, plus filters `a`/`c`/`u`.
  - Right: the SIFT steps pane, and an evidence pane with citations, the parent text and the trace URL.
  - The audio assessment flow (`A`) keeps working within this mode.
- **Verify:** unit tests check:
  - `JevClient` builds the request (model, state keys, choice criteria) and parses `choice`, `confidence` and `probabilities` from a recorded response fixture
  - the evidence module returns all four SIFT fields with a stubbed LM, and has no verdict output
  - the gate on hedged, interrogative and declarative fixtures
  - a missing framework writes `skipped_no_framework` and leaves `fact_check_passed` NULL
  - a stubbed LM verdict appends a row and a second run appends another row
  - the renderer shows the filter and columns
  
  Update the existing `tests/unit/tui/test_assessment_view.py` to match.

### 11. Compile and generate as jobs (fact 37)
- `start_compile` and `start_generate` (`views/compiler_gen.py:253` and `:433`) enqueue `compile` and `generate` jobs with their payloads. The handlers wrap `_run_compile` and `_run_generate`, and `compiler_state` is still updated for the Compiler view's in-place display.
- Remove `compiler_task`.
- **Verify:** update `tests/unit/tui/test_compiler_gen.py` so the start functions enqueue jobs. A handler test checks that `compiler_state` is updated.

### 12. Topic model job (facts 36, 38)
- `topic_model` handler:
  - Load all active-run child texts and their 768-dimensional vectors from `embeddings`.
  - Run `BERTopic(embedding_model=None, min_topic_size=…)` with `.fit_transform(docs, embeddings=np.array(vectors))`, so nothing is re-embedded.
  - Write `topic_runs`, `topics` (label from `get_topic_info`, top keywords) and `clauses.topic_id`.
  - One item per phase: load, UMAP/HDBSCAN fit, write.
- **Verify:** a unit test with 60 synthetic children in three separable vector clusters checks that three or more topics are written and every child has a `topic_id` (BERTopic runs for real; the fixture is small). The renderer test checks that the topic label appears in the Ingest detail pane.

### 13. Re-ingest the archive and run end-to-end checks (fact 25)
- After step 2 truncates the tables, queue `ingest` with the `recursive` strategy for every notebook. This is a manual step through the TUI, or a one-off loop using `JobStore.enqueue`. Then queue one `topic_model`.
- Spot-check in the TUI:
  - the Jobs tab shows several jobs, at most 2 running
  - the Ingest mode shows parents, children, tokens and deps
  - a Langfuse trace link opens
- **Verify:**
  - `psql` counts: clauses > 0, `count(*) where parent_id is null` = 0, `chunk_runs` has one active row per document
  - mypy and the full pytest suite (fact 40):
    ```
    uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports
    uv run pytest -n auto --dist loadgroup
    ```
    Check the exit status directly, without piping.

## Risks and open questions
- **Rate of dynamic-window LLM calls.** Running it across the archive costs one ChainOfThought call per parent. Recursive is the default for the archive re-ingest; dynamic-window runs per notebook through `r`.
- **Fact-check runtime.** At a median of 55 s per check, even a gated notebook can take hours. Two workers share one model endpoint, so the throughput gain may be small.
- **BERTopic resource use on this host.** UMAP over roughly 45k × 768 vectors needs a few GB of RAM. If it runs out of memory, set `low_memory=True` on UMAP or fit on a sample and `transform` the rest.
- **SIFT signature change.** Moving from a boolean to a 3-way verdict plus steps changes model behavior. Langfuse traces from the first runs should be compared against the old `fact_check_passed` distribution.
- **The Jev Decisions API is an alpha endpoint** (`/api/alpha/decisions`), so its request shape may change. All calls go through `JevClient` so a change touches one file. Unit tests stub the HTTP layer. One opt-in live test (marked `e2e`, needs `OPENROUTER_API_KEY`) sends a single decision request.
- **The confidence threshold for accepting a verdict isn't set yet.** For now every verdict is stored with its confidence. A threshold such as "supported below 0.8 is shown as low-confidence" can be picked later from a hand-labeled sample, following the Jev classification cookbook.
- **The check-worthiness gate could also use Jev:** a yes/no question, "is this a checkable factual assertion?", asked with the child's SFL output as state. It's left out of this goal; the SFL-only gate comes first, and Jev can be added once some gate rejections have been reviewed.
- **CI is not the gate on this fork.** CI does not install the `assessment` extra (which now holds `redis`), and recent fork runs were skipped. No Redis service was added to CI. Local runs against live Redis are the gate.
- **Thread safety of `TUIState`.** Handlers mutate shared state (`compiler_state`, `notebook_stats`) from worker threads. Writes should be limited to whole-key assignment, with the job store as the source of progress data.
- **`external_id` format change.** Code that splits `external_id` on `:`, such as the assessment chunk mapping, must be audited. Run `grep -rn "external_id" src/` in step 2.

## Wave 0 status (2026-10-10, implemented by Opus)
Steps 1–3 are done, plus the interface stubs. Every file below is a contract for wave 1. Change these signatures only in wave 2.
- `_app/tracing.py`: `job_span(kind, **attrs) -> trace_id | None`, `current_trace_id()`, `trace_url(trace_id)`.
- `db/models.py` with migration `f2c1a7d4e9b0`, applied to localhost:5435 (legacy clauses truncated): `ChunkRun`, `ParentChunk`, `TopicRun`, `Topic`, `FactCheck` (`job_id` column, not `run_id`), and `FACT_CHECK_VERDICTS`. `Clause` gains `run_id`, `parent_id`, `sfl` and `topic_id`. `alembic check` reports no drift.
- `tui/jobs/store.py`: `JobStore`, `JobStatus`, `ItemStatus`, `connect()` (raises `RedisUnavailable`), `NOTEBOOKLM_REDIS_URL`.
- `tui/jobs/runner.py`:
  - `JobRunner` and `JobCancelled`.
  - `JobContext`: `phase`, `check_cancelled`, `add_item`, `item_running`, `item_done`, `item_skipped`, `item_failed`, `acquire_token`, `payload`, `notebook_id`, `state`, `trace_id`.
  - The handler contract is `async def handle(ctx) -> str | None`.
- `tui/jobs/kinds.py` with `handlers/<kind>.py` stubs: each wave-1 agent replaces only its own stub.
- `tui/state.py`: `Mode`, `MODE_LABELS`, `VIEW_MODE`, `state.mode`, `set_mode`, `job_store`, `job_runner`, `refresh_jobs_snapshot`, `running_jobs`, `jobs_view`, `ingest_view`, `factcheck_view`. `consume_token` is behind a lock.
- `tui/app.py`: checks Redis at startup and exits with status 2 if it's unreachable, recovers interrupted jobs, starts the runner, and redraws while jobs run.
- `_preprocessing/chunking/`: `base.py` (`ChildChunk`, `ParentChunk`, `ChunkStats`, `ChunkResult`, the `ChunkStrategy` protocol and offset invariants) and the `STRATEGIES`/`make_strategy` registry.
- `_preprocessing/jev.py`: the `JevClient.decide(state, questions) -> dict[str, Decision]` stub, plus `ChoiceQuestion` and `Decision`.
- Tests: `tests/unit/tui/jobs/` (live Redis; fails when Redis is unreachable), `tests/unit/_app/test_tracing.py`, `tests/unit/db/test_models_schema.py`. All 32 pass.
- Already failing before this work, and not caused by it: 6 guardrail tests and `test_claude_md_freshness`.
