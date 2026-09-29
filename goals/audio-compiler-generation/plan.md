# Plan: Audio Compiler Generation (compile → review → edit → generate, from the TUI)

Facts: [`facts.md`](facts.md) (20 accepted; 17 with automated verification. Fact 3 was revised and facts 18–20 were added in plan review: auto-extract now uses RRF over ingested clauses, with NotebookLM chat as the fallback).

## Solution approach

This is a personal tool, not an upstream PR, so there is no restructuring:
- The compiler stays in `examples/notebooklm-audio/compiler/` and is loaded through the existing `tui/compiler_bridge.py`.
- Generation uses the same client calls as `notebooklm generate audio` / `runner.py`: `artifacts.generate_audio` → `wait_for_completion` → `download_audio`.

New code is limited to:
1. A small module, `tui/views/compiler_gen.py`, holding the compile/generate workers and sidecar writing.
2. Compiler-view state and keys.
3. An `$EDITOR` handoff that suspends the Live display.
4. Rendering.
5. Two `runner.py` fixes.

## Ordered steps

### Step 1: Compile against the selected notebook (facts 1–3, 8 partly)
- `tui/compiler_bridge.py`:
  - Add `load_audio_project(path) -> AudioProjectConfig`, using the same `sys.path` loading as `compile_audio_project`.
  - Add `compile_audio_config(config) -> str`.
  - Import the `compiler.*` modules in one place, so the `sys.modules` deletion happens once per call and not in the middle of a compile.
- `tui/views/compiler_gen.py`:
  - `start_compile(state)`: requires `state.selected_notebook`; otherwise sets the error "select a notebook first".
  - It submits `_run_compile` to a background executor. `_run_compile`:
    - loads the YAML;
    - sets `config.notebook_id = selected`, on the in-memory config only;
    - if `auto_extract` is set, runs `auto_populate_from_notebook(client, nb, config, verbose=False)`. `verbose=False` is required because stdout output corrupts the Live screen;
    - on an extraction exception, keeps the YAML values and sets `compiler_state["warning"]`;
    - compiles and stores `prompt`, `edited=False`, `project`, `notebook_title`, `audio_format`, `audio_length`.
  - `compiler_state["phase"] = "compiling"` drives the spinner.
- `tui/views/compiler_view.py::compile_selected` delegates audio YAMLs to `start_compile`. Video YAMLs keep the current preview-only behavior.
- **Verify:** `tests/unit/tui/test_compiler_gen.py` monkeypatches the bridge and client and checks:
  - `notebook_id` is overridden and the YAML file's mtime and bytes are unchanged;
  - with auto_extract, the extract function is called with the selected id;
  - an extract exception produces a warning and the fallback prompt;
  - no selected notebook produces an error and no worker is started.

### Step 1b: RRF-grounded slot filling (facts 3, 18–20)
- `src/notebooklm/_app/clause_search.py`: add `async rrf_search(session, document_ids, query, top_k=8, k=60, embedder=None) -> list[MatchedClause]`:
  - keyword list: `Clause.text` matched with `func.to_tsvector('english', Clause.text).op('@@')(func.websearch_to_tsquery('english', query))`, ranked by `ts_rank`, top 25. It uses the existing `idx_clauses_tsv` index, so no migration is needed;
  - vector list: the same `l2_distance` join as `search_clauses`, top 25;
  - fusion: `score = Σ 1/(k + rank)` over both lists, returning the top_k clauses;
  - it makes no LLM call and does not call `setup_dspy_router()`.
  - `search_clauses` is not changed.
- `tui/views/compiler_gen.py::fill_slots_from_clauses(client, session, nb_id, config, lm) -> SlotFill`:
  1. `document_ids = await _notebook_document_ids(client, nb_id)`. If it is empty, or no clauses exist → return `None`, and the caller falls back to `auto_populate_from_notebook(verbose=False)` and sets a warning (fact 3).
  2. One `rrf_search` per slot group, with queries built from `config.topic` plus a slot hint: agreement / confirmed checkpoint; confusion / desync or mismatch; frustration / bottleneck or exhaustion; brainstorm / open speculative question; mechanisms and topics; compound failure escalations.
  3. One `dspy.Predict(CompilerSlotSignature)` call. Inputs: topic plus the retrieved clauses labelled `[C<n>]`. Outputs: the four lexical strings, 3–4 topics, up to 2 escalations, and the `[C<n>]` ids cited for each slot. It runs inside `with dspy.context(lm=lm):`.
  4. Write the outputs into the in-memory config and return `SlotFill(evidence={slot: [clause_id, text]})`.
- `start_compile` (main thread) calls `setup_dspy_router()` once, captures `lm = dspy.settings.lm`, and passes `lm` to the worker (fact 20).
- Preview: an `Evidence` section under the prompt (dimmed), one line per slot: `agreement ← C3, C7`, where each label maps to the start of the clause text. The sidecar gains `slot_evidence` (fact 19).
- **Verify:**
  - `tests/unit/_app/test_rrf_search.py`: RRF fusion math on fixed rank lists (a clause ranked in both lists outranks one ranked only in a single list); `top_k` is respected. The SQL is exercised against the local Postgres if `DATABASE_URL` is reachable, otherwise that test is skipped.
  - `test_compiler_gen.py`:
    - with no document ids, the chat fallback is used and the warning is set;
    - with clauses present, a fake `dspy.Predict` output lands in config slots and in `evidence`;
    - `setup_dspy_router` is patched to raise if called outside the main thread, and the test asserts the worker never calls it (fact 20).

### Step 2: Map format and length (fact 8, fact 14)
- `compiler_gen.py::to_audio_enums(fmt, length) -> (AudioFormat | None, AudioLength | None)`:
  - `"default"` or empty → `None`;
  - otherwise the value is uppercased with `-` replaced by `_` and looked up in `notebooklm.rpc.types.AudioFormat` / `AudioLength`;
  - an unknown value raises `ValueError` naming the valid choices. This happens at compile time, so the preview shows the error.
- `examples/notebooklm-audio/runner.py::execute_audio_pipeline` passes `audio_format` / `audio_length` through the same mapping. The mapping is duplicated as a 6-line helper to avoid importing from `tui`.
- **Verify:** parametrized tests for all four formats, all three lengths, `"default"`, and the invalid value. A runner test with a fake client asserts that `generate_audio` receives the enums.

### Step 3: `runner.py --emit` (fact 13)
- Add an `--emit` flag. It requires `-n`, runs auto-bind with `verbose=False`, and prints **only** the compiled prompt to stdout. Diagnostics go to stderr.
- **Verify:**
  - A unit test with a fake client captures stdout and checks it equals `compile_audio_prompt(config)` with no banner lines.
  - Manual: `runner.py proj.yaml -n <nb> --emit | notebooklm generate audio --prompt-file - -n <nb> --no-wait`.

### Step 4: `$EDITOR` handoff (fact 6)
- `keypress.py`: in `View.COMPILER`, `e` (with a compiled prompt present) sets `state.compiler_state["edit_requested"] = True`. The key handler cannot touch the terminal itself.
- `app.py` main loop: when `edit_requested` is set,
  1. `live.stop()`;
  2. restore cooked terminal mode, via a new `suspend_raw_terminal()` context manager in `keypress.py` that runs `termios` restore and then re-enters cbreak;
  3. write the prompt to a temp file (`tempfile.NamedTemporaryFile(suffix=".md", delete=False)`);
  4. run `subprocess.run([editor, path])` with `editor = $EDITOR or shutil.which("nvim") or "vi"`;
  5. read the file back; if the text changed, set `prompt=new`, `edited=True`;
  6. remove the temp file;
  7. `live.start(refresh=True)`.
  - An editor that is missing or exits non-zero leaves the prompt unchanged and shows an error.
- **Verify:** unit test on a helper `edit_prompt_via_editor(text, run=subprocess.run)` with a fake `run` that rewrites the file. It covers: changed → `edited=True`; unchanged → `edited=False`; non-zero exit → the original is kept. The Live suspend/resume is checked manually (fact 6 row in the manual checklist).

### Step 5: Confirm, generate, download, sidecar (facts 7–12)
- `keypress.py`, Compiler view:
  - `g` (with a prompt, and no generation running) sets `compiler_state["confirm"] = True`;
  - `y` calls `start_generate(state)`;
  - `n` / `Esc` clears confirm and makes no call.
- `_run_generate` (background):
  1. `phase=submitted` → `generate_audio(nb, instructions=prompt, audio_format, audio_length)`;
  2. `phase=generating` → `wait_for_completion(timeout=1200)`;
  3. `phase=downloading` → `download_audio(nb, path, artifact_id)`;
  4. `phase=done` and the path is shown.
  - `started_at` is recorded, and the renderer computes the elapsed time.
  - Any exception or non-complete status sets `phase=failed`, `error`, and `artifact_id` (if known). The prompt and the `edited` flag are left unchanged, so `g` retries (fact 12).
  - Rate-limit errors reuse the client's `--retry` backoff helper if it is exposed. Otherwise a single attempt is made and the error is shown.
- Output path: `~/Archive/NotebookLM/audio/<project-slug>/<YYYYMMDD-HHMM>_<notebook-slug>.mp3`, with parent directories created. The directory is overridable with `$NOTEBOOKLM_AUDIO_DIR`, to keep tests off `$HOME`.
- Sidecar `<same>.json` is written on success **and** failure. It holds:
  - `project_yaml`, `template`, `notebook_id`, `notebook_title`, `artifact_id`, `audio_format`, `audio_length`
  - `prompt` (exact text sent), `edited`
  - `started_at`, `finished_at`, `status`, `error`
- **Verify:** tests with a fake client (in `tests/unit/tui/test_compiler_gen.py`):
  - the `instructions` argument equals the edited prompt byte for byte;
  - the enums are passed through;
  - the phases occur in order;
  - the MP3 and sidecar paths match the pattern (using `tmp_path` and the env override);
  - the sidecar fields are complete on success;
  - on failure: the sidecar has the error, the phase is `failed`, and the prompt and edited flag are kept;
  - `n` / `Esc` on the confirm panel makes zero client calls;
  - `g` during a running generation does nothing.

### Step 6: Rendering, look, key hints, docs (facts 4, 5, 9, 15, 16)
- `tui/renderers/compiler.py`, list panel:
  - YAML rows with `audio`/`video` chips;
  - the selected row in the accent color with the `▌` marker;
  - a dimmed line naming the target notebook: `→ <notebook title>`, or `no notebook selected` in the warning color.
- Preview panel:
  - a header line: `project · notebook · format · length · N chars`. The count uses the `warning` style above 5,000 characters and `muted` otherwise;
  - an `edited` chip when edited;
  - a `warning` line for the extract fallback;
  - the prompt body, scrolled with `j`/`k` (`compiler_state["scroll"]`). The existing `Syntax(markdown)` renderer is kept, but only the visible window of lines is rendered.
- Confirm panel: a rounded-border panel replacing the preview, listing notebook, project, format, length, chars, edited, and `y send · n cancel`.
- Status line: `phase` with a spinner character, plus elapsed time as `mm:ss`; on `done` the file path; on `failed` the error and artifact id in the `danger` style.
- Use the existing `_widgets.panel` and theme tokens (`accent`, `muted`, `warning`, `danger`, `border.focus`). Add no new colors. Rounded borders come from `box.ROUNDED` in `panel` if not already set.
- `renderers/footer.py`: Compiler-view hints `enter compile · e edit · g generate · j/k scroll · esc back`.
- `app.py`: keep redrawing each tick while `phase` is in `compiling|submitted|generating|downloading`, so the elapsed time and spinner update.
- `docs/tui-reference.md`: add a "Compiler: generate audio" section.
- **Verify:**
  - Renderer tests assert the header text includes the char count; the warning style applies at 5,001 characters but not at 5,000; and the `edited` chip, confirm panel text, failed error text, and `→ notebook` line appear.
  - Manual visual check of the look.

### Step 7: Gates and one live run
- `uv run pytest tests/unit/tui -q` and the full `uv run pytest -n auto --dist loadgroup`, checking the exit status directly.
- `uv run mypy src/notebooklm --ignore-missing-imports` and `uv run ruff check src tests examples/notebooklm-audio`.
- One real generation, which is the goal's purpose: in the TUI, select the SFL notebook (`3da35aa6…`), press `p`, choose `sfl-engine-pipeline-mechanics.yaml`, Enter, `e` (make a small edit), `g`, `y`. Wait for the MP3.
  - Confirm the sidecar prompt equals `notebooklm artifact get-prompt <artifact_id>`. This shows whether NotebookLM stored the full 4.5k-character prompt or truncated it.

## Risks / open questions

1. **Server-side prompt length.** The compiled prompt is 4,584 characters, and NotebookLM's limit is undocumented. The Step 7 comparison with `artifact get-prompt` shows whether it is truncated. If it is, the warning threshold in fact 5 is changed to the real limit.
2. **Editor handoff under `Live(screen=True)`.** `live.stop()` has to leave the alternate screen, and cbreak mode must be restored before nvim starts, or nvim gets garbled input. This is isolated in Step 4 and checked manually.
3. **The `sys.modules` deletion in `compiler_bridge`.** Compiling a video YAML and then an audio YAML in one session reloads the `compiler` package each time. It works for one compile at a time. Step 1 prevents two compiles from overlapping by refusing a new compile while `phase == compiling`.
4. **Slot quality depends on ingestion coverage.** RRF can only ground slots in clauses that were ingested. A notebook with a few ingested sources gives narrow vocabulary. The Evidence section shows this before sending. The chat fallback (`auto_bind.py`) still uses heuristic line parsing and is not improved here.
6. **Embedding model mismatch.** `rrf_search` must embed the query with the same adapter used at ingestion (`OllamaEmbeddingAdapter`, 768-dimension). If Ollama is down, the vector list is empty and RRF falls back to keyword-only ranking, with a warning, instead of failing the compile.
5. **Background thread + client.** Each worker calls `asyncio.run(...)` with its own `NotebookLMClient.from_storage()`, following the existing pattern, which satisfies the one-client-per-event-loop rule.
