# Plan: Fork separation + fresh `sfl-ingest` project

## Solution approach

Two tracks. **Track A (this repo):** capture a stable fork-vs-upstream manifest from the fork's own 93 commits, then merge upstream `main` (344 commits ahead) into `development` and prove the suite still passes. **Track B (fresh project):** scaffold `/home/b08x/WorkspaceV3/sfl-ingest` as its own uv project that depends on `notebooklm-py` from PyPI (never vendored), lift the fork's ingest subsystems into a new `sfl_ingest.*` namespace (rewrite fork-internal imports, keep `notebooklm.*` facade imports pointing at the installed package), and assemble the TUI/REST/MCP surfaces on top of upstream's extension seams (`create_app()`, `register_all(mcp)`, `register(mcp)`).

Key seam findings from exploration:
- `IngestionService.ingest_source` already covers url/text/file/drive via `client.sources.add_* → wait_until_ready → get_fulltext`; notes are already handled in the TUI ingest handler (`tui/jobs/handlers/ingest.py:54-82` ingests sources **and** notes); audio = `artifacts.download_audio → TranscriptionService → ingest_chunks` (`_app/artifact_ingest.py`, fork-internal imports only); deep-research = upstream `client.research.import_sources_with_verification` (`_app/research.py`) followed by the normal source ingest loop.
- Upstream exposes assembly points: `server/app.py:create_app()` (+ `app.state` mutation and `include_router` post-construction), `mcp/server.py:register_all(mcp)` (fork added `tools/clauses.py`, whose `register(mcp)` is its own seam).
- `jobs/runner.py` is pure asyncio (no Redis); DB is Postgres+pgvector via `db/` + `alembic/`; embeddings via `OllamaEmbeddingAdapter` (`_preprocessing/embeddings.py:29`).
- The fork's REST/MCP/test lift targets are fork-added files (`server/routes/corpus.py`, `routes/factcheck.py`, `mcp/tools/clauses.py`, `tests/server/test_corpus_routes.py`, …); `server/app.py`, `mcp/server.py`, `cli/*` are fork-*modifications* of upstream files.

## Ordered steps

### Track A — separation in this repo

**A1. Generate the fork manifest (before merging, so it snapshots the pre-merge boundary).**
- Build `goals/fork-separation-ingest/fork-manifest.md` from `git log --name-status development --not main` (93 commits), cross-checked against `git diff --name-status <merge-base>..development`.
- Classification per path: **fork-added** (created by fork commits), **upstream-modified** (fork edited a file that exists on `main`), **shared** (changed by both fork and upstream since the last sync — conflict-prone; currently ~71 files incl. `pyproject.toml`, `uv.lock`, `server/app.py`, `mcp/server.py`, `cli/*`, `_artifacts.py`, docs, example compilers).
- Generator lives in the goal dir (e.g. `goals/fork-separation-ingest/gen_manifest.py`).
- **Verify:** script exits non-zero if any fork-touched path is missing from the manifest; `test -s goals/fork-separation-ingest/fork-manifest.md`; counts match `git rev-list --count development --not main` = 93 commits.

**A2. Merge upstream into `development`.**
- `git fetch upstream` (origin is the fork; upstream = teng-lin/notebooklm-py — add remote if absent), update local `main`, then `git merge main` on `development`.
- Resolve conflicts path-by-path using the manifest's `shared` section as the pre-briefed list; for `uv.lock` regenerate with `uv lock`; for docs/prompts + example compilers prefer upstream content unless the fork goal dir documents a deliberate divergence.
- **Verify:** clean `git status`; `uv run pytest -n auto`; `uv run ruff check .`; `uv run mypy src/notebooklm` — all green on `development` (facts `fact-merge`, `fact-tests-post-merge`).

### Track B — fresh project

**B1. Scaffold `sfl-ingest`.**
- `uv init` + project setup at `/home/b08x/WorkspaceV3/sfl-ingest`; `[project] name = "sfl-ingest"`; deps: `notebooklm-py` (PyPI), plus fork-lift deps as they land (sqlalchemy[asyncio], asyncpg, alembic, pgvector, httpx/ollama, spacy, textual, fastapi, mcp, dspy…); extras `browser`/`cookies` mirroring upstream auth options; `src/sfl_ingest/` layout, `tests/` with pytest config.
- **Verify:** `uv run python -c "import notebooklm, sfl_ingest"`; `uv run pytest` passes (empty); `grep notebooklm-py pyproject.toml`; no `src/sfl_ingest/**` file duplicates upstream module names like `client.py`/`rpc/` (facts `fact-project-exists`, `fact-pypi-dep`).

**B2. Lift preprocessing core + DB.**
- Copy `_preprocessing/` → `src/sfl_ingest/preprocessing/` (chunking/, chunkers, embeddings, ingestion, features, pipeline first; fact_check/jev/sift/sfl_engine come in B5) and `db/` + `alembic/` → `src/sfl_ingest/db/`, `sfl-ingest/alembic/`.
- Import rewrite: fork-internal `from .._preprocessing / notebooklm.db / notebooklm._app` → `sfl_ingest.*`; upstream facade imports (`notebooklm` client types) stay.
- **Verify:** `uv run ruff check . && uv run mypy src`; `alembic upgrade head` against local Postgres creates `chunk_runs/parent_chunks/clauses/embeddings`; unit test: `IngestionService.ingest_text` with a fake client + fake embedder writes parent/child rows (facts `fact-storage`).

**B3. Library ingest API for the four NotebookLM source types (url, text, file, drive).**
- New `src/sfl_ingest/sources.py`: `ingest_url/ingest_text/ingest_file/ingest_drive(notebook_id, …)` each doing `client.sources.add_* → wait_until_ready → IngestionService.ingest_source`, plus a thin `sfl-ingest` CLI entry over them.
- Lift `scope`/`tracing`/`corpus` query helpers from `_app/` as needed for verification.
- **Verify:** pytest per source type with a recorded/fake `NotebookLMClient` (no network): assert add_* called, fulltext chunked, rows in pgvector (facts `fact-url`, `fact-text`, `fact-file`, `fact-drive`).

**B4. Audio, notes, deep-research paths.**
- Audio: lift `_app/artifact_ingest.py` + `_preprocessing/{transcription,audio_prep}.py`; `ingest_audio_artifact(notebook_id, artifact_id)` = download → transcribe (default deepgram, provider via env) → `ingest_chunks`.
- Notes: port the TUI handler logic (`tui/jobs/handlers/ingest.py:54-82`) into `ingest_notebook_notes(notebook_id)` using `client.notes.list` + content fetch → `ingest_text`.
- Deep-research: `client.research.import_sources_with_verification` → loop `ingest_source` over the imported source ids.
- **Verify:** three pytest suites with fake transcriber / fake notes client / fake research client (facts `fact-audio`, `fact-notes`, `fact-deep-research`).

**B5. Lift remaining subsystems (fact-check/SFL, TUI, REST, MCP).**
- Fact-check/SFL: `_preprocessing/{fact_check,jev,sift,sfl_engine,checkworthiness,annotators}` + `_app/{fact_checks,factcheck_runs,sfl_tagging,sfl_format,assessment*}` → `sfl_ingest/{assessment,sfl}/`.
- TUI: lift `tui/` wholesale → `src/sfl_ingest/tui/` with import rewrite; own Click entry `sfl-ingest tui` (does **not** patch upstream's CLI).
- REST: lift `server/routes/{corpus,factcheck}.py`, fork parts of `server/_corpus.py`, fork deltas of `server/app.py` → `sfl_ingest/server/`; assembly function that calls upstream `create_app()`, then sets `app.state.corpus = CorpusServices()` and `include_router`s the lifted routers under upstream's versioned prefix (confirm prefix during implementation); port `tests/server/test_{corpus,factcheck}_routes.py` + `conftest/_corpus_env/_live`.
- MCP: `sfl-ingest mcp` entry creating its own `FastMCP`, calling upstream `notebooklm.mcp.server.register_all(mcp)` then lifted `clauses.register(mcp)`.
- **Verify:** `uv run pytest tests/` fully green incl. subsystem tests; import-contract test asserting upstream imports resolve to site-packages `notebooklm` (fact `fact-subsystems`).

**B6. Scope guard + final gate.**
- Test asserting no web frontend exists (`not Path("web").exists()` and no `*.tsx`) (fact `fact-no-web-ui`); full `uv run pytest && uv run ruff check . && uv run mypy src` in both repos (facts `fact-tests-fresh`, `fact-tests-post-merge`).

## Verification summary (automated)

| Fact | Check |
|---|---|
| fact-merge | `git status` clean; merge commit present; no conflicts |
| fact-tests-post-merge | `uv run pytest -n auto && uv run ruff check . && uv run mypy src/notebooklm` in notebooklm-py |
| fact-manifest | generator self-check + `test -s fork-manifest.md` + counts = 93 |
| fact-project-exists | path + `[project] name = "sfl-ingest"` |
| fact-pypi-dep | `notebooklm-py` in pyproject deps; no vendored upstream modules |
| fact-url/text/file/drive | per-path pytest (fake client) asserting pgvector rows |
| fact-audio/notes/deep-research | per-path pytest (fake transcriber/notes/research) |
| fact-storage | `alembic upgrade head` + vector-column assert; `OllamaEmbeddingAdapter` used |
| fact-subsystems | import/existence tests per lifted subsystem + REST route tests |
| fact-no-web-ui | no `web/` or `*.tsx` in sfl-ingest |
| fact-tests-fresh | `uv run pytest` green with per-source-path test modules |

## Risks / open questions

1. **Upstream merge is large (344 commits, ~71 shared files).** API drift may break fork code that patches upstream internals (`server/app.py`, `mcp/server.py`, `cli/*`) — budget a dedicated conflict-resolution pass; manifest's `shared` list is the pre-briefed worklist.
2. **REST lift couples to upstream `create_app` internals** (`Depends(get_client)`, state keys). Pin `notebooklm-py` version and add an import-contract test so upstream bumps fail loudly.
3. **Heavy test dependencies:** spacy model download, dspy/LM calls, real Ollama, Postgres. Unit tests use fake embedder/client/transcriber; mark integration tests (`-m integration`) for Ollama/Postgres; keep everything green without network by default.
4. **Auth for any live smoke test** needs `notebooklm login` (browser or `--browser-cookies`) — keep live e2e behind an opt-in marker; facts are verified with fakes.
5. **Notes content fetch API** (`notes.get` vs list payload) confirmed during B4; deep-research source-id enumeration may need `sources.list` filtering — resolve while implementing.
6. **Manifest-before-merge ordering** is deliberate (stable snapshot); if the merge reveals misclassification, regenerate from the fork commit set (unchanged by merges).
