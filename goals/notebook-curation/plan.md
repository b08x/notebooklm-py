# Plan — Notebook Curation (delete, add/remove items, archive-then-delete)

Facts: [`facts.md`](facts.md) (20 accepted; 16 require automated verification. Facts 19–20 were added from plan review).

## Solution approach

- **Business logic goes in two new modules in `src/notebooklm/_app/`:**
  - `curation.py`: remove items, add a source, delete a notebook.
  - `archive.py`: collect, tar, verify, and finalize an archive, then delete remotely.
  - Neither module imports `tui`, `click`, or `rich` (fact 17).
- **The TUI only handles modal state, key dispatch, rendering, and background workers.** It uses the existing pattern in `tui/views/notebook_detail.py`: `ThreadPoolExecutor` → `asyncio.run(...)` → a fresh `NotebookLMClient.from_storage()` plus `async_session_maker()`.
- **Two new Postgres tables** record removals and archived notebooks: `removal_log` and `archived_notebooks` (facts 4, 14). Existing `clauses`, `embeddings`, and `local_assets` rows are never deleted.
- **Archive is a staged pipeline that fails closed:**
  1. Collect into a staging directory.
  2. Write `<name>.tar.gz.partial`.
  3. Verify it.
  4. Rename to `.tar.gz` only if there are zero `failed` items and verification passes.
  5. Delete remotely only after that, and only after typed-title confirmation.
- **Each archive item gets one of three statuses:** `ok`, `failed`, or `not_downloadable`.
  - `not_downloadable` covers uploaded-file originals, for which no RPC exists. It is listed in the manifest and does not block the delete.
  - `failed` always blocks the delete (fact 12).
- **The existing TUI "Download assets" action (`_download_assets_async`) is not changed.** It ignores failures silently, which is correct for a convenience download and wrong for archive-then-delete, so archive does not reuse it.

## Ordered steps

### Step 1 — DB schema: removal log + archived-notebook record
- `src/notebooklm/db/models.py`: add two tables.
  - `RemovalLog`: `id`, `created_at`, `notebook_id`, `notebook_title`, `item_id`, `item_title`, `item_type` (`source|artifact|note|mind_map|notebook`), `action` (`remove|delete_notebook|archive`), `reason`, `archive_path` (nullable).
  - `ArchivedNotebook`: `id`, `created_at`, `notebook_id` (indexed), `title`, `archive_path`, `document_ids` (JSONB list), `reason`, `remote_deleted` (bool).
- `alembic/versions/<rev>_add_removal_log_and_archived_notebooks.py`: a new revision after `d3f8a1c9b2e4`.
- **Verify:**
  - `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` against the local DB.
  - A unit test in `tests/unit/test_db_models_curation.py` asserts the table and column names from `Base.metadata`.

### Step 2 — `_app/curation.py` (facts 1–8, 17)
- `REMOVAL_REASONS = ("redundant", "incorrect", "experimental", "hallucinated", "other")`.
- `CurationItem(kind, id, title)`.
- `async list_curation_items(client, nb_id) -> list[CurationItem]`: returns sources, artifacts, notes, and mind maps.
- `async execute_remove_items(client, session, nb_id, nb_title, items, reason) -> RemovalResult(removed, failed: list[(item, error)])`:
  - Raises `ValueError` if `reason` is not in `REMOVAL_REASONS`, before any network call.
  - Dispatches each item to `sources.delete` / `artifacts.delete` / `notes.delete` / `notes.delete_mind_map`.
  - Writes one `RemovalLog` row per successful removal.
  - Continues past individual failures.
- `validate_add_source(kind, value) -> str | None`: `url` must be non-empty and http(s); `file` must be an existing regular file; `text` must be non-empty. Performs no I/O beyond `Path.is_file()`.
- `async execute_add_source(client, nb_id, kind, value)`: routes to `sources.add_url` / `add_file` / `add_text`. YouTube URLs go through `add_url`, which already routes them.
- `title_confirmation_matches(title, typed) -> bool`: case-insensitive prefix match. The typed text must be at least `min(len(title), 4)` characters.
- `async execute_delete_notebook(client, session, nb_id, nb_title, reason)`: calls `notebooks.delete` and writes a `RemovalLog` row (`item_type="notebook"`).
- **Verify:** `tests/unit/_app/test_curation.py` uses a fake client and an in-memory fake session. It covers:
  - A reason is required.
  - A partial-failure batch logs only the successes.
  - An invalid path or empty input makes zero client calls.
  - Prefix-confirmation rules.
  - Each item kind is dispatched to the right delete method.

### Step 3 — `_app/archive.py` (facts 9–14, 17)
- `archive_root()`: returns `$NOTEBOOKLM_ARCHIVE_DIR` or `~/Archive/NotebookLM`, and runs `mkdir(parents=True, exist_ok=True)`.
- `archive_filename(title, nb_id, date)`: returns `<slugified-title>_<id[:8]>_<YYYYMMDD>.tar.gz`.
- `async collect_archive(client, session, nb_id, staging, progress_cb) -> ArchiveManifest`. Staging layout:
  - `sources/<slug>.md`: full text via `sources.get_fulltext(output_format="markdown")`.
  - Source originals: the manifest records `url` for web sources. Uploaded originals are marked `not_downloadable`.
  - `artifacts/<slug>.<ext>`: native format, using the same kind→method→extension table as `notebook_detail.py:248-292`.
  - `notes/<slug>.md` and mind maps.
  - `chat_history.md`: via `chat.get_history`.
  - `db/clauses.jsonl` and `db/embeddings.jsonl`: every `Clause` whose `document_id` is in (source ids ∪ artifact ids ∪ note ids), plus their `Embedding` rows.
  - `manifest.json`: notebook metadata, reason, and per-item `{id, title, type, created_at, archive_path, status, error}`. Artifact entries also carry `kind`, `artifact_status`, and the generation prompt/instructions when the artifact metadata exposes them (fact 20), so a later compiler goal can regenerate them.
  - `progress_cb(done, total)` is called after each item (fact 15).
- `write_tarball(staging, dest_partial)` → `verify_archive(path, manifest) -> VerifyResult(ok, file_count, total_bytes, missing, empty)`. Verification checks:
  - `tarfile.open` succeeds.
  - Every `status == "ok"` entry is present with size > 0.
  - `manifest.json` is present.
- `finalize_archive(partial, manifest, verify)`: renames `.partial` → `.tar.gz` only if there are zero `failed` items and `verify.ok`. Otherwise the `.partial` file is kept.
- `async record_archive(session, manifest, path, reason, remote_deleted)`: writes the `ArchivedNotebook` row and a `RemovalLog` row (`action="archive"`).
- `async execute_archive_delete(client, session, archive_result, typed_title)`:
  - Refuses unless the archive was finalized and `title_confirmation_matches`.
  - Calls `notebooks.delete` and sets `remote_deleted=True`.
- **Verify:** `tests/unit/_app/test_archive.py` uses a fake client that writes bytes and uses `tmp_path`. It covers:
  - Filename format, and the directory is created if missing.
  - The manifest lists every item type and the tarball contains every `ok` path.
  - An injected download failure → `.partial` kept, no `.tar.gz`, and `notebooks.delete` never called.
  - A truncated or zero-byte entry fails verification.
  - A declined confirmation → the notebook is not deleted and the archive stays.
  - The clause/embedding JSONL contains only that notebook's `document_id`s.
  - No delete is issued against `Clause`, `Embedding`, or `LocalAsset`.

### Step 4 — TUI state + key dispatch (facts 1–3, 6–8, 13)
- `tui/state.py` adds a single `curation: dict[str, Any]` modal slot. It follows the `assessment_state` precedent and avoids adding many flat fields. Sub-modes:
  - `items`: the mark list; cursor; `marked` ids.
  - `confirm_yn`: lists the marked items.
  - `reason`: keys `1`–`5`.
  - `add_kind`: `u` URL, `f` file, `t` text.
  - `add_input`: a text buffer.
  - `typed_confirm`: a notebook-title buffer.
  - `archive_progress` and `archive_result`.
- `tui/keypress.py`: a new early-return block `if state.curation:`, like the existing `selecting_sources` block, so the modal captures all keys. New Notebook Detail keys (none of these are currently bound in Notebook Detail):
  - `m`: open the item list. `space` marks an item, `x` removes the marked items (→ reason → y/N), `Esc` closes.
  - `+`: add a source (→ kind → input → Enter).
  - `D`: delete the notebook (→ reason → typed title).
  - `X`: archive the notebook (→ reason → background archive → verification summary → typed title to delete remotely, or `Esc` to keep the remote notebook).
- Workers go in a new `tui/views/curation_view.py`, following the `_run_*`/`start_*` pairs in `notebook_detail.py`. On success they refresh the item list or the sources, and after a notebook delete they remove the notebook from `state.notebooks`, `notebook_stats`, and the `tui_cache`.
- `tui/app.py`: poll `curation` progress each tick while an archive runs, the same way `background_task` is polled.
- **Verify:** `tests/unit/tui/test_curation_keypress.py` drives `handle_key` sequences against `TUIState`, with worker functions monkeypatched. It covers:
  - Mark/unmark; `x` without a reason does not dispatch.
  - `N`/`Esc` cancels with zero calls.
  - An invalid file path shows an error and does not dispatch.
  - A typed-title mismatch blocks the delete.
  - After a delete the notebook disappears from `get_filtered_and_sorted_notebooks()`.

### Step 4b — Notes in the ingestion picker (fact 19)
- `tui/views/notebook_detail.py::_fetch_sources_async` also returns `notes.list(nb_id)`, wrapped so each item carries `kind="note"`. Mind maps are excluded because they are JSON, not prose.
- `_ingest_notebook_async` handles `kind == "note"` by calling `service.ingest_text(session, document_id=note.id, text=note.content)`. Sources keep using `ingest_source`.
- The picker renders a `[note]` tag. The "already ingested" check already works per `document_id`.
- **Verify:** extend `tests/unit/tui/test_notebook_detail.py`:
  - A selected note calls `ingest_text` with the note's id and content.
  - An unselected note is skipped.
  - Sources still go through `ingest_source`.

### Step 5 — Rendering, key hints, docs (facts 5, 11, 15, 16)
- `tui/renderers/main.py` renders the modal panels:
  - the item list with type tags and mark state;
  - the y/N list;
  - the reason picker;
  - the input prompt;
  - archive progress (`n/total`);
  - the verification summary (file count, human-readable size, list of failed/missing items);
  - the list of partial-failure removals.
- The footer (`render_footer`) shows the new keys when Notebook Detail is active.
- `docs/tui-reference.md` gets a "Curation" section with every new key and the archive layout.
- **Verify:**
  - Additions to `tests/unit/tui/test_renderers.py` check that the rendered text contains the item titles, the reason options, the `n/total` progress, the verification counts, and the failed-item titles.
  - Manual: run `uv run python -m notebooklm.tui` and check that the UI stays responsive during an archive.

### Step 6 — Gate + live smoke test
- `uv run pytest tests/_guardrails/test_app_boundary.py`
- `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports`
- `uv run ruff check src tests && uv run ruff format --check src tests`
- `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` (exit status checked directly, not piped).
- Manual live smoke test on a **throwaway notebook**, created with `notebooklm create "curation-smoke"` and given 1 URL source, 1 text source, 1 report, and 1 note:
  1. Add a source.
  2. Remove 2 items with a reason.
  3. Archive, and inspect the tarball with `tar tzf`.
  4. Decline the delete, then archive again and confirm.
  5. Check that the notebook is gone from the sidebar and that the `removal_log` and `archived_notebooks` rows exist.

## Risks / open questions

1. **Uploaded-file originals cannot be downloaded.** No RPC returns the original bytes, only full text. Under this plan they are recorded as `not_downloadable` and do not block the delete. If you require original binaries for uploads, the only option is to keep a local copy at add time, which is out of scope here.
2. **Artifacts that are still generating or failed.** These are recorded as `not_downloadable`, with `kind`, `artifact_status`, and any known generation prompt in the manifest (fact 20). They do not block the delete. Regenerating them from compiler YAML templates (`examples/notebooklm-{audio,video}/projects/*.yaml` via `tui/compiler_bridge.py`) is a separate goal: `goals/compiler-regenerate-artifacts/` (stub created with this goal). **Resolved in part:**
- `Artifact.generation_prompt` (`_types/artifacts.py:206`, #1571/#1925) is already filled in by `artifacts.list()` from the `LIST_ARTIFACTS` response, including for failed artifacts. The manifest records it with no extra RPC.
- The manifest records `generation_prompt: null` when:
  - the artifact was generated with no custom prompt (the default template);
  - it is a note-backed mind map;
  - Google moved the prompt to a different array position (the read is guarded).
- **Survey (2026-09-29, 367 notebooks, 3,410 artifacts):** 79.3% have a prompt. By kind:
  - report 100%, slide_deck 98%, data_table 96%, infographic 96%, audio 94%, video 86%
  - mind_map 4% (0% before 2026-05); flashcards 4%
  - file and unknown 0%
- Prompts exist back to 2024-10. Blanks in later months are scattered, which matches default-template generation, not an age cutoff.
- The compiler goal must match mind maps and flashcards by `kind`, not by prompt.

7. **Unhandled artifact kinds.** The survey found `file` (28, since 2026-08) and `unknown` (3) artifacts. The kind→download-method table has no entry for either.
   - Step 3 must mark any kind without a download method as `not_downloadable` (with its `kind` recorded), not as `failed`. Otherwise every recent notebook would fail archive verification.
   - Add a unit test for it.
   - Before implementing, find out what `file` artifacts are: check `ArtifactTypeCode` in `_types/artifacts.py` and one live example. They may be downloadable through `media_urls`.
3. **Archive size.** Videos and audio can be hundreds of MB. Staging is placed in a hidden directory under `~/Archive/NotebookLM/.staging/` (same filesystem, so the final rename is atomic) and is removed after finalize.
4. **Rate limiting.** Every download is spaced 0.5 s apart, as in the existing download path. Large notebooks take minutes, and the progress display covers this.
5. **Threading.** Worker threads change `state.curation` in place, as the existing ingestion and assessment workers do. No DSPy calls are involved, so the `dspy.configure` thread rule does not apply.
6. **Clause ownership for notes.** After Step 4b, notes can be ingested under `document_id = note.id`, and the archive DB export includes them. A note deleted in the Step 2 removal flow keeps its clauses locally, because rows are never purged.
