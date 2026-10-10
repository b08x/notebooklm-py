# Goal: TUI job queue, Ingest/Fact-check workbench, parent/child chunking

Turn the notebooklm-py TUI into a workbench for compiling the notebook archive into a traceable corpus. Every long-running action becomes a manually triggered job: it is stored in Redis and appears in a Jobs tab. The archive is re-ingested into Postgres/pgvector as parent/child chunks with spaCy features, using three chunking strategies (recursive, cluster-semantic, dynamic-window). New Ingest and Fact-check modes, modeled on Tree Ring Memory, show the chunks, their linguistic features, SFL tags, SIFT evidence, Jev verdicts and BERTopic topics. Every job and stored result links to its Langfuse trace.

- Shared understanding: [facts.md](facts.md) (41 facts; ids and verification flags in [facts.meta.json](facts.meta.json))
- Execution plan: [plan.md](plan.md) (13 ordered steps, each with a check)
- Decision record: [grill-notes.md](grill-notes.md)

Context, not a deliverable: the corpus feeds a planned channel called "Mr. and Mrs. Language Model", which will carry persona-prompted audio overviews and short articles.

## Done condition
- Every fact in facts.md holds.
- Each fact with `automatedVerification: true` has a passing automated test, or a documented blocker in plan.md.
- `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports` exits 0.
- `uv run pytest -n auto --dist loadgroup` exits 0, with the exit status checked directly, not through a pipe.
- The archive has been re-ingested: `clauses` contains no row with a NULL `parent_id`, and every ingested document has exactly one active `chunk_runs` row.
- A manual TUI session shows several queued jobs in the Jobs tab with at most two running, the Ingest mode with tokens and deps for real data, and a working Langfuse trace link.
