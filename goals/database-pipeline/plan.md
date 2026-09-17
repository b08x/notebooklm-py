# Database Pipeline Implementation Plan

## Solution Approach
We will build an async PostgreSQL database pipeline using SQLAlchemy 2.0, asyncpg, and pgvector-python. The database schema will strictly mirror the `sfl-engine`'s `clauses` and `embeddings` tables to serve as a compatible add-on backend. We will also scaffold a new `notebooklm-tui` executable as the frontend for this data layer. Migrations will be handled via Alembic.

## Ordered Steps

1. **Dependency & Entrypoint Updates**
   - Update `pyproject.toml` to add `sqlalchemy`, `asyncpg`, `pgvector`, and `alembic` to the `dependencies` list.
   - Add a new `notebooklm-tui = "notebooklm.tui.__main__:main"` console script in `pyproject.toml`.
   - **Verification:** Run `uv sync` and verify dependencies install without conflict. Run `notebooklm-tui --help` to ensure the script is recognized (after Step 5).

2. **Initialize Database Models (`src/notebooklm/db/models.py`)**
   - Define a SQLAlchemy declarative base.
   - Implement the `Clause` model (fields: `id`, `external_id`, `text`, `document_id`, `sentence_index`, `root_index`, `tokens` [JSONB], `groups` [JSONB], `created_at`).
   - Implement the `Embedding` model (fields: `id`, `clause_id` [FK to clauses.external_id], `embedding` [Vector(768)], `model`, `created_at`).
   - Set up the HNSW index on the `embedding` column and GIN index on `text`.
   - **Verification:** Run `python -c "from notebooklm.db.models import Base"` without import errors.

3. **Initialize Database Connection & Session (`src/notebooklm/db/session.py`)**
   - Implement an async database connection manager using `create_async_engine` and `async_sessionmaker`.
   - Source the connection string from the environment (e.g., `DATABASE_URL`).
   - **Verification:** Write a short pytest unit test to verify that the session maker can be instantiated and connects successfully (assuming a test database is available) or mocks properly.

4. **Scaffold TUI Entrypoint (`src/notebooklm/tui/__main__.py`)**
   - Create the file and implement a basic `main()` function (likely using Click, given the project's existing CLI patterns).
   - Add a simple command group structure.
   - **Verification:** Run `uv run notebooklm-tui --help` and verify it outputs the scaffolded help text.

5. **Alembic Setup and Initial Migration**
   - Run `alembic init -t async alembic` to create the async migration environment.
   - Configure `alembic.ini` and `alembic/env.py` to point to the `notebooklm-py` async engine and `Base.metadata`.
   - Run `alembic revision --autogenerate -m "Initial schema: clauses and embeddings"`.
   - **Verification:** Inspect the generated migration file to ensure it correctly creates the pgvector extension (if needed) and the `clauses` and `embeddings` tables. Run `alembic upgrade head` on a local Postgres instance to confirm it applies cleanly.

## Risks & Open Questions
- **Vector Extension:** The initial migration must ensure the `vector` extension is created (`CREATE EXTENSION IF NOT EXISTS vector;`) before defining the `embeddings` table. We may need to manually inject this into the generated migration.
- **FTS Index:** SQLAlchemy's `to_tsvector` equivalent for the `idx_clauses_tsv` GIN index needs to be expressed correctly using `Index` and `func.to_tsvector`.
