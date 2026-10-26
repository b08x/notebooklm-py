# Goal: Fork separation + fresh multi-source ingest project

Separate the fork's logic from upstream `teng-lin/notebooklm-py` — by capturing a fork manifest and merging latest upstream `main` into `development` — and build a fresh project **`sfl-ingest`** (`/home/b08x/WorkspaceV3/sfl-ingest`) that depends on `notebooklm-py` from PyPI and ingests URL, text, file, Google Drive, audio-artifact, notes, and deep-research inputs end-to-end into Postgres + pgvector.

- Shared understanding: [`facts.md`](facts.md) (16 accepted facts)
- Execution plan: [`plan.md`](plan.md) (Track A: manifest + upstream merge in this repo; Track B: scaffold, lift, integrate, verify in `sfl-ingest`)

## Done condition

The fork/upstream manifest exists under `goals/fork-separation-ingest/` and this repo's `development` branch carries the upstream merge with a green suite; `sfl-ingest` depends on PyPI `notebooklm-py` (no vendored upstream code), contains the lifted subsystems (preprocessing core, DB/alembic, corpus orchestration, transcription/audio, fact-check/SFL, TUI, REST corpus routes, MCP clause tools — no web UI), and its `uv run pytest` passes covering every selected v1 source-type ingest path end-to-end (add → fulltext → chunk → embed → pgvector).
