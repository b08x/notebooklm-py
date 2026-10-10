# Grill notes: TUI job queue and workbench layout

Session date: 2026-10-10. Decisions are listed in the order they were resolved.

## Context (stated by the user, not a deliverable)
The long-term goal is to distill the notebook archive into a Substack-style channel called "Mr. and Mrs. Language Model". It would carry audio overviews generated with persona prompts, plus short articles. This goal builds the tooling that makes that possible. It does not build the channel.

## Decisions
1. **Queue scope:** one general job model for every background job kind (download, ingest, sfl_tag, fact_check, and later compile). The tab is titled "Jobs". Downloads are the first kind moved onto it.
2. **Job state:** stored in Redis and executed inside the TUI process (no separate worker daemon).
   - Each job is a hash at `nblm:job:<id>`, indexed by the sorted sets `nblm:jobs:queued` and `nblm:jobs:all`.
   - Jobs left `running` when the TUI starts are marked `interrupted` and can be re-queued.
   - Downloads resume without duplicating work, because finished assets are recorded in `LocalAsset`.
   - Redis db0 is shared with Ruby Gush (`gush.jobs.*`) and Ohm (`AnnotatedClause*`). This code must only touch keys under `nblm:`.
3. **Concurrency:** two workers by default, set by `NOTEBOOKLM_TUI_JOB_WORKERS`. All workers share the existing API token bucket. Each job keeps a per-item child list at `nblm:job:<id>:items` with name, kind, status and bytes.
4. **Navigation:** a mode bar under the header, `1 Notebooks │ 2 Ingest │ 3 Fact-check │ 4 Compiler │ 5 Jobs (n▸) │ 6 Logs`.
   - Number keys switch modes, and the existing letter keys keep working.
   - Each mode has its own pane layout; the notebook sidebar appears only where a mode uses it.
   - Chat moves under Notebooks as an action.
5. **Parent/child chunking:** in scope.
   - Ingest is a per-notebook job.
   - SFL tagging is a separate job kind (`sfl_tag`), run after the deterministic spaCy pass.
   - The Ingest mode shows spaCy attributes: POS, morphology, dependencies and clause/token groups.
6. **Storage:** Postgres and pgvector hold all derived text: parents, children, transcripts and parses. Redis holds job state only. If Redis is lost, the recovery path is to reprocess from source. The Redis snapshot settings checked on this host (RDB only, AOF off, up to one hour of loss) motivated this choice.
7. **Chunking strategies in this goal:**
   - The recursive splitter, in the order `\n\n` → `\n` → `. ? !` → spaCy sentence fallback (the last resort) → space split above a token limit.
   - An entity-aware boundary guard.
   - A strategy interface with provenance in `chunk_runs`: strategy, parameters, version, Langfuse trace id and source-text hash.
   - The spaCy pass 1 stored per child.
   - **ClusterSemanticChunker.**
   
   Deferred: dynamic window (DSPy), topic, dependency-based, summary-as-child and schema-based strategies. Not planned: HTML, Markdown and row-serialization strategies.
8. **Code location:** all code lives in notebooklm-py. intentAS is a shelved brainstorm; do not reference it.
9. **Ingest mode layout:** modeled on Tree Ring Memory.
   - Left pane: sources, notes and transcripts, with their parents and child-count bars.
   - Right pane: the selected parent's children above a token detail pane that toggles between `[t]okens`, `[d]eps` and `[g]roups`.
   - Dependencies are shown as a flat table (token, POS, dep, → head, morphology).
   - Keys: `r` re-runs ingest with a chosen strategy; `x` compares two runs using per-run aggregate counts stored in `chunk_runs`.
10. **Fact-check:**
    - A `fact_checks` table appends one row per check: verdict enum `supported`/`contradicted`/`unverifiable`/`skipped_no_framework`, the four SIFT steps as JSON, citations, trace id, model and latency. `Clause.fact_check_passed` is set from the newest verdict.
    - A deterministic check-worthiness gate uses spaCy features (declarative mood, modality cue, asserting verb); children it rejects are marked `not_checkworthy`.
    - Layout: a claims list with a verdict filter, a SIFT steps pane, and an evidence/context pane showing the parent text and the trace link.

## Facts established by codebase checks
- `state.background_task` and `state.download_progress` are single slots. `start_download` creates a new one-worker executor on every call (`tui/views/notebook_detail.py:323`).
- `build_layout()` returns one fixed tree with header, sidebar, results/detail and footer (`tui/layout.py`).
- The DB holds 45,729 clauses across 193 documents, none of which has a parent (Postgres at localhost:5435).
- The Python package has no `redis` client. `langfuse` is not installed. Tracing goes through OpenTelemetry using `openinference.instrumentation.dspy` to an OTLP endpoint on Langfuse (`_app/assessment.py:102`).
- The embedder is Ollama `embeddinggemma` with 768-dimensional vectors (`_preprocessing/embeddings.py`).
- The current fact-check stores only a boolean, discards citations, and records a pass when the framework file is missing.
