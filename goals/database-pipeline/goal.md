# Goal: Implement Database Pipeline

Build an asynchronous PostgreSQL database pipeline using SQLAlchemy 2.0 and pgvector, exactly mirroring the `sfl-engine` schema (clauses and embeddings) to serve as a compatible add-on backend. Scaffold a new `notebooklm-tui` executable to act as the primary frontend interface for this data layer. 

- **Facts:** See [facts.md](facts.md) for the shared understanding of technical requirements and schema specifics.
- **Plan:** See [plan.md](plan.md) for the step-by-step execution plan and verification steps.

## Done Condition
- `SQLAlchemy`, `asyncpg`, `alembic`, and `pgvector` are added to the project dependencies.
- The `Clause` and `Embedding` models match the `sfl-engine` schema and are successfully exported.
- The async database connection session manager is implemented.
- The `notebooklm-tui` console script is scaffolded in `pyproject.toml` and executes successfully.
- An initial Alembic migration is generated that successfully creates the `vector` extension and the two tables.
