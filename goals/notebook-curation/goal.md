# Goal — Notebook Curation (delete, add/remove items, archive-then-delete)

## Articulated Goal

Add curation actions to the NotebookLM TUI so redundant, incorrect, experimental, and hallucinated material can be separated from material worth keeping:
- Add sources. Mark and remove sources, artifacts, notes, and mind maps. Every removal requires a reason and is logged.
- Delete a notebook.
- Archive a notebook: write a verified `.tar.gz` to `~/Archive/NotebookLM` containing sources, artifacts, notes, chat history, and a local clause/embedding export, then delete the remote notebook only after verification passes and the user confirms by typing the title.
- Notes can be ingested into the local clause DB.

Local Postgres data is never purged. Archived notebooks stay findable through an `archived_notebooks` record.

## Reference

- **Facts:** [`facts.md`](facts.md). 20 accepted facts, which are the shared understanding. Per-fact verification flags are in [`facts.meta.json`](facts.meta.json).
- **Plan:** [`plan.md`](plan.md). The approved execution plan, Steps 1–6 including 4b: DB schema → `_app/curation.py` → `_app/archive.py` → TUI state/keys → note ingestion → rendering/docs → gates and live smoke test.
- **Out of scope:** cross-notebook chat, distillation/annotation, article generation, archive restore, multi-notebook batch, and CLI/MCP archive commands. Compiler-based artifact regeneration is stubbed at [`../compiler-regenerate-artifacts/goal.md`](../compiler-regenerate-artifacts/goal.md).

## Done Condition

- Every fact with `automatedVerification: true` has a passing unit test. The tests are in `tests/unit/_app/test_curation.py`, `tests/unit/_app/test_archive.py`, `tests/unit/tui/test_curation_keypress.py`, `tests/unit/tui/test_renderers.py`, `tests/unit/tui/test_notebook_detail.py`, and `tests/unit/test_db_models_curation.py`.
- The Alembic migration upgrades and downgrades cleanly against the local DB.
- `tests/_guardrails/test_app_boundary.py`, mypy, ruff, and the CI-equivalent `pytest -n auto --dist loadgroup --cov-fail-under=90` all pass, with the exit status checked directly.
- `docs/tui-reference.md` documents the new keys (`m`, `x`, `+`, `D`, `X`) and the archive layout.
- The live smoke test on a throwaway notebook passes:
  1. Add a source.
  2. Remove items with a reason.
  3. Archive, and inspect the tarball with `tar tzf`.
  4. Decline the delete and confirm the notebook is kept.
  5. Archive again, confirm the delete, and check the notebook is gone and the `removal_log` and `archived_notebooks` rows exist.
