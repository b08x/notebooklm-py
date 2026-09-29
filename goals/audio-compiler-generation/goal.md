# Goal: Audio Compiler Generation (compile → review → edit → generate, from the TUI)

## Articulated Goal

Generate NotebookLM audio overviews from the compiler's YAML projects and Jinja2 templates directly in the TUI, replacing copy-paste in the browser:
1. Pick a project YAML in the Compiler view and bind it to the notebook selected in the sidebar.
2. Fill the template slots from the notebook's **curated, ingested clauses** using hybrid RRF retrieval (full-text + pgvector) and one LLM call. NotebookLM chat is the fallback when nothing is ingested.
3. Review the compiled prompt and the supporting evidence, and edit it in `$EDITOR`.
4. Confirm and generate with the YAML's format and length.
5. The MP3 and a sidecar recording the exact prompt sent are saved to `~/Archive/NotebookLM/audio/`.

This is a personal tool. The compiler stays in `examples/`.

## Reference

- **Facts:** [`facts.md`](facts.md). 20 accepted facts (shared understanding); per-fact verification flags are in [`facts.meta.json`](facts.meta.json).
- **Plan:** [`plan.md`](plan.md). The approved plan: Steps 1, 1b, and 2–7.
- **Evidence:** [`prompt-survey-2026-09-29.txt`](prompt-survey-2026-09-29.txt), a per-month × kind count of stored generation prompts.
- **Next goal:** [`../audio-script-molding/goal.md`](../audio-script-molding/goal.md) (transcript → edited script → supertonic/ElevenLabs TTS). Its decisions are already recorded.

## Done Condition

- Every fact marked `automatedVerification: true` has a passing unit test. The tests are in `tests/unit/tui/test_compiler_gen.py`, `tests/unit/_app/test_rrf_search.py`, the renderer tests, and the runner tests.
- `uv run pytest -n auto --dist loadgroup`, mypy, and ruff all pass, with exit status checked directly.
- One live run on the SFL notebook completes end to end:
  - RRF-filled slots with the Evidence section shown;
  - an edit made in `$EDITOR`;
  - the edit sent after `y`;
  - the MP3 and sidecar written.
- For that run, `notebooklm artifact get-prompt <artifact_id>` matches the sidecar prompt, or any truncation is recorded and the warning threshold in fact 5 is adjusted to match.
- `docs/tui-reference.md` documents the Compiler-view keys.
