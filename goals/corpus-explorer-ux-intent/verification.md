# Verification: Corpus Explorer QA remediation inside current tabs

Manual and automated verification record for `goal.md`. Updated as execution proceeds.

## Step 0 — Baseline (2026-10-12)

- Working tree at start: clean; the Step 0 precondition edits were already committed as `bfd6d025` ("feat(ui): map empty state, runs table scroll, contrast fixes").
- `ux-qa.mp4` is not present anywhere in the repo; no `.gitignore` change needed.
- Baseline commands (all exit 0):
  - `uv run pytest tests/server tests/unit/_app -q` → **456 passed** in 119.76s
  - `cd web && pnpm test` → **67 passed** (17 files), 4.03s
  - `cd web && pnpm typecheck` → **clean** (no output, exit 0)
- Follow-up goal stub created: `goals/corpus-explorer-workflow-ia/README.md` (fact 28).

## Steps 1–9

(pending)
