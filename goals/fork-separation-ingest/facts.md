# Facts

- Latest upstream `main` (teng-lin/notebooklm-py) is merged into this repo's `development` branch, with no conflicts remaining and a clean working tree.
- After the upstream merge, this repo's own test suite (`uv run pytest`, ruff, mypy) passes on `development`.
- A fork manifest exists at `goals/fork-separation-ingest/fork-manifest.md` listing every file the fork touched, each marked as fork-added, upstream-modified, or shared.
- A fresh project `sfl-ingest` exists at `/home/b08x/WorkspaceV3/sfl-ingest` with package name `sfl-ingest`.
- `sfl-ingest` depends on `notebooklm-py` from PyPI and does not vendor a copy of upstream notebooklm source code.
- The fresh project ingests a web URL end-to-end: add_url → wait until ready → get_fulltext → chunk → embed → row stored in pgvector.
- The fresh project ingests raw pasted text end-to-end through the same chunk → embed → pgvector path.
- The fresh project ingests an uploaded file end-to-end: add_file → ready → fulltext → chunk → embed → pgvector.
- The fresh project ingests a Google Drive file end-to-end: add_drive → ready → fulltext → chunk → embed → pgvector.
- The fresh project ingests an audio artifact: download the audio, transcribe it, and store each transcript turn as parent/child chunks with embeddings.
- The fresh project ingests a notebook's notes into the same corpus tables as other sources.
- The fresh project ingests the sources produced by a deep-research run once the research completes.
- The fresh project stores chunks in Postgres + pgvector, embeds with Ollama (`embeddinggemma-300m`), and manages its schema with alembic migrations.
- The fresh project contains the lifted fork subsystems: preprocessing core (chunkers/embeddings/IngestionService), corpus orchestration, transcription/audio, fact-check/SFL engine, Textual TUI + job queue, REST corpus routes, and MCP clause tools.
- The fresh project has no web UI: the React Corpus Explorer frontend is out of scope.
- The fresh project's automated test suite (`uv run pytest`) passes, covering every selected v1 source-type ingest path.
