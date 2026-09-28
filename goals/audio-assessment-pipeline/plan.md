# Plan: Audio Overview Assessment Pipeline

## Solution Approach

Move all preprocessing/scoring orchestration out of `tui/views/assessment_view.py` into a
new `_app/assessment.py`-owned entry point (extending the existing `generate_assessment`
module), wire a real data path from `notebook_detail` (new menu action) into that entry
point instead of the hardcoded sample text, add contextual embedding of the transcript to
that path, and upgrade the Contextualized Source Chunks panel from plain concatenated text
to Rich-styled entity colors + fact-check gutters. Add spaCy (`en_core_web_md`) as a real,
provisioned extra while leaving BERTopic/Docling soft-optional as they are today.

## Ordered Steps

1. **Add an `_app`-layer orchestration entry point, sourcing the real transcript via the
   existing transcription adapters (revised per plan review)**
   - Per plan-review feedback, `audio_metadata` should not be an invented string from
     `Artifact` fields — the audio overview should be "treated as a regular transcript,
     for example when using deepgram," reusing the transcription abstraction that already
     exists in `_preprocessing/transcription.py` (`DeepgramAdapter`, `AssemblyAIAdapter`,
     `SpeechmaticsAdapter`, `TranscribeCppAdapter`, `TranscriptionService`) rather than
     inventing a new metadata shape.
   - Add `run_full_assessment(client, session, notebook_id, artifact_id) -> AssessmentResult`
     to `src/notebooklm/_app/assessment.py`. It should: resolve the audio artifact via
     `client.artifacts.get_or_none`/`get_artifact` (`_app/artifacts.py:get_artifact`),
     download it locally by reusing the existing `_app/download.py` machinery
     (`build_download_plan`/`execute_download`, the same code the CLI's `download audio`
     command already drives — no new download path needed), run the local file through
     `TranscriptionService(adapter).transcribe_audio()` with a configurable adapter
     (default `DeepgramAdapter`, reading `DEEPGRAM_API_KEY` like the interview example;
     `TranscribeCppAdapter` for a fully local/offline path — **noted as still in progress
     per the plan-review comment, "I'm still working on how to transcribe with diarize
     locally," so step 1 should make the adapter pluggable via
     `NOTEBOOKLM_ASSESSMENT_TRANSCRIBE_PROVIDER` rather than hardcode Deepgram, but doesn't
     need to finish the local-diarization path itself**), and use the adapter's return dict
     directly: `text` becomes the transcript fed to `PreprocessingPipeline.process()`, and
     `diarization`/`provider` become `audio_metadata` (no separately-invented Artifact-field
     string).
   - Also fetch the generation prompt via `get_artifact_prompt` as `system_instructions`,
     and ingest the transcript into the same `clauses`/`embeddings` tables the notebook's
     regular sources use, treating it as another source under the parent notebook (per
     plan-review feedback: "it would be treated another source under the parent
     notebookID") — see step 1b — then call `generate_assessment()`.
   - Return a typed result (chunks with structured per-chunk metadata — entities list, topic
     id, `clause_external_id` for the fact-check hookup in step 6 — not pre-flattened
     strings) so the TUI can render colors/gutters instead of parsing formatted text back
     apart.
   - Files touched: `src/notebooklm/_app/assessment.py`.
   - Guardrail: this module must stay `click`/`rich`/`tui`-free, per
     `tests/_guardrails/test_app_boundary.py` (same boundary rule documented in the module's
     existing docstring).

1b. **Reuse `IngestionService` for the transcript instead of an ad-hoc embed call**
   - `IngestionService.ingest_source()` (`_preprocessing/ingestion.py`) currently couples
     "fetch full text from `client.sources`" with "chunk + embed + persist into
     `clauses`/`embeddings`" in one method. Extract the chunk+embed+persist half into a new
     `ingest_text(session, document_id, text)` method that `ingest_source` calls after it
     resolves `fulltext.content`, so `run_full_assessment` (step 1) can call
     `ingest_text(session, document_id=artifact_id, text=transcript)` directly — the audio
     transcript becomes a `Clause`/`Embedding` row set keyed by the artifact's id, stored
     alongside the notebook's other sources' clauses, giving the "contextual semantic
     embedding" fact (fact-1) a real, queryable destination instead of a throwaway vector
     list.
   - Files touched: `src/notebooklm/_preprocessing/ingestion.py`.

2. **Adjust `PreprocessingPipeline.process()` to return structured chunks**
   - Change return type from `list[str]` to a small dataclass/TypedDict per chunk (`text`,
     `topic_id`, `entities: list[tuple[str, str]]`, `fact_check_passed: bool`) instead of a
     pre-formatted string blob, so downstream renderers can use the structured fields for
     color/gutter rendering. Keep a `.formatted` convenience property or helper for any
     caller that still wants the flattened text (e.g. tests, fallback plain rendering).
   - Files touched: `src/notebooklm/_preprocessing/pipeline.py`,
     `src/notebooklm/_preprocessing/__init__.py` (export `PreprocessingPipeline` and the new
     chunk type — currently `__init__.py` only exports transcription symbols).

3. **Wire notebook_detail → assessment (real data path)**
   - Add a 4th detail-menu action ("Assess Audio Overview") in `notebook_detail.py`,
     following the `start_download`/`start_ingestion` pattern: resolve the notebook's audio
     artifacts via `client.artifacts.list(notebook_id)`, and if one exists, populate
     `state.assessment_state` by calling the new `_app.assessment.run_full_assessment` in a
     background thread, then switch `state.current_view = View.ASSESSMENT`. If no audio
     artifact exists, surface `state.error_message` instead of entering the view.
   - Bump `keypress.py`'s `detail_menu_index` clamp from `2` to `3` and add the branch for
     index `3`.
   - Files touched: `src/notebooklm/tui/views/notebook_detail.py`,
     `src/notebooklm/tui/keypress.py`.
   - This removes the `raw_text` sample-text fallback path in
     `trigger_assessment_grading`/`assessment_view.py` for the real-data case (fact-2); the
     sample fallback can stay only for when `assessment_state` is entered with nothing
     populated (e.g. direct `A` keypress with no notebook context), which is existing
     behavior, not a regression to fix here.

4. **Simplify `assessment_view.py` to a thin renderer**
   - Replace `trigger_assessment_grading`'s pipeline/`generate_assessment` calls with a call
     into the new `_app.assessment` entry point (background-thread submission stays in the
     view/keypress layer, matching the existing `notebook_detail.py` pattern used elsewhere
     in this codebase — only the *what to run* moves to `_app`, not the threading).
   - Remove the direct `from notebooklm._preprocessing.pipeline import PreprocessingPipeline`
     import from `assessment_view.py`.
   - Files touched: `src/notebooklm/tui/views/assessment_view.py`.

5. **Entity color-highlighting in the chunk panel**
   - Build a `rich.text.Text` per chunk instead of a plain string: append the chunk body,
     then re-render entity spans with `Text.stylize()` using a small label→style map (e.g.
     `PERSON` cyan, `ORG` green, `DATE`/`GPE` yellow, fallback style for other labels) driven
     by the structured `entities` field from step 2.
   - Compose the per-chunk `Text` objects with `rich.console.Group` (or a `Table`/`Columns`
     if a gutter column is added — see step 6) inside the existing `Panel` in
     `AssessmentView.render()`.
   - Files touched: `src/notebooklm/tui/views/assessment_view.py`.

6. **Fact-check pass/fail gutters as an opt-in, persisted action (revised per plan review)**
   - Per plan-review feedback, fact-checking should not run unconditionally inline in
     `PreprocessingPipeline.process()`. Instead: `PreprocessingPipeline.process()` drops the
     `FactCheckAdapter` call entirely (step 2's structured chunk has no `fact_check_passed`
     field at pipeline time). The gutter starts in a neutral "not checked" state (`?` styled
     dim) for every chunk.
   - Add a migration (new file under `alembic/versions/`, following
     `226e0b882afd_initial_schema_clauses_and_embeddings.py`'s pattern) adding a nullable
     `fact_check_passed: bool | None` column to `Clause` (`src/notebooklm/db/models.py`), so
     a result can be "stored in the chunks table" per the review feedback.
   - Add a keybinding in the `View.ASSESSMENT` branch of `keypress.py` (e.g. `f`) that runs
     `FactCheckAdapter.check()` for the currently-scrolled-to chunk (or all loaded chunks, if
     that proves simpler than tracking a per-chunk cursor) via the `_app` layer, persists the
     result onto the matching `Clause.fact_check_passed` row (keyed by the
     `clause_external_id` step 1 attached to each chunk), and updates the gutter glyph
     (`✓` green / `✗` red) once the background task completes.
   - **UI disclosure for the always-pass fallback (per plan review: "make that clear in the
     UI").** Add a `framework_available: bool` property to `FactCheckAdapter`
     (`os.path.exists(self.framework_path)`, already computed in `check()` — just expose it)
     and surface it through the `_app.assessment.run_fact_check_for_chunk` result. When
     `framework_available` is `False`, render the gutter as a distinct dim/yellow `✓*` (not
     the same green as a real pass) and show a one-line banner in the Assessment Controls
     panel — e.g. `"⚠ SIFT framework not found at <path> — fact-check results are
     unverified (always pass)"` — so a user never mistakes a default-pass result for a real
     one.
   - Files touched: `src/notebooklm/db/models.py`, new `alembic/versions/*.py`,
     `src/notebooklm/_preprocessing/pipeline.py`, `src/notebooklm/_preprocessing/fact_check.py`,
     `src/notebooklm/tui/views/assessment_view.py`, `src/notebooklm/tui/keypress.py`,
     `src/notebooklm/_app/assessment.py` (a `run_fact_check_for_chunk` entry point).

7. **spaCy as a real extra (`en_core_web_md`)**
   - In `pyproject.toml`'s `assessment` extra, keep `spacy` pinned as-is; add the
     `en_core_web_md` model as a direct pip-installable wheel URL dependency (spaCy models
     are published as regular wheels, e.g.
     `en_core_web_md @ https://github.com/explosion/spacy-models/releases/download/en_core_web_md-<version>/en_core_web_md-<version>-py3-none-any.whl`)
     so `uv sync --extra assessment` provisions the model without a separate `spacy download`
     step. Update `SpacyAnnotator.__init__` and `StructuralCoherenceChunker`'s hardcoded
     `"en_core_web_sm"` default to `"en_core_web_md"`.
   - Update `docs/installation.md`'s `assessment` extra row — it currently lists
     `nltk`/`rouge-score`/`librosa`, which do not match `pyproject.toml`'s actual
     `spacy`/`bertopic`/`docling`/`dspy-ai` — to describe the real dependency set and the
     `en_core_web_md` provisioning step.
   - Files touched: `pyproject.toml`, `docs/installation.md`,
     `src/notebooklm/_preprocessing/annotators.py`, `src/notebooklm/_preprocessing/chunkers.py`.
   - **Scoped to local for this pass (per plan review, "let's get it working locally
     first"):** `CLAUDE.md`'s canonical contributor install doesn't include `--extra
     assessment`, so CI still only exercises `_preprocessing/`'s ImportError-fallback branch
     after this goal — that's accepted for now. `uv sync --extra assessment` locally is the
     verification target; wiring `--extra assessment` into
     `.github/workflows/test.yml` (and its coverage-gate implications per CLAUDE.md's own
     blind-spot warning) is a separate follow-up decision, not part of this plan.

8. **Tests**
   - `tests/unit/preprocessing/test_pipeline.py` (new): structured-chunk output shape (no
     `fact_check_passed` field at pipeline time), including the fallback path when
     spaCy/BERTopic aren't importable.
   - `tests/unit/preprocessing/test_ingestion.py`: extend for the new `ingest_text()` method
     (step 1b) — same chunk/embed/persist behavior as `ingest_source`, minus the
     `client.sources.get_fulltext` call.
   - `tests/unit/tui/test_notebook_detail.py`: new menu action populates `assessment_state`
     from a mocked client (no audio artifact → error_message set, not a view switch).
   - `tests/unit/tui/test_assessment_view.py`: extend to assert entity styling spans appear
     for known entities, and that the gutter renders the neutral `?` glyph before any
     fact-check has run and the `✓`/`✗` glyph once `assessment_state`'s per-chunk
     `fact_check_passed` is set; assert no `PreprocessingPipeline`/`generate_assessment`
     import remains in `assessment_view.py` (a simple `ast`/source-grep guardrail test,
     mirroring the project's existing `tests/_guardrails/` pattern, satisfies fact-3's
     automated verification cheaply without mocking the whole background-thread flow).
   - `tests/unit/tui/test_keypress.py`: extend for the new `f` (run fact-check) keybinding in
     `View.ASSESSMENT`.
   - `tests/unit/preprocessing/test_annotators.py`: assert `SpacyAnnotator`/
     `StructuralCoherenceChunker` default to `en_core_web_md`.
   - New Alembic migration (step 6) gets exercised the same way the existing two versions
     are — no dedicated test beyond `uv run alembic upgrade head` against the
     `deploy/docker-compose.db.yml` database succeeding.

## Verification for Each Step

- **Step 1–1b–2:** `uv run pytest tests/unit/preprocessing/test_pipeline.py tests/unit/preprocessing/test_ingestion.py -v`
  (transcription mocked at the `TranscriptionAdapter.transcribe()` boundary); manually run
  the flow with a real `DEEPGRAM_API_KEY` set against a notebook with a generated audio
  overview, and inspect the `clauses`/`embeddings` tables to confirm the transcript's
  clauses appear alongside the notebook's regular source clauses.
- **Step 3–4:** `uv run pytest tests/unit/tui/test_notebook_detail.py tests/unit/tui/test_keypress.py -v`;
  manually run `uv run notebooklm-tui`, select a notebook with a generated audio artifact,
  choose "Assess Audio Overview", confirm real system instructions/metadata appear (not the
  sample-text placeholder).
- **Step 5–6:** `uv run alembic upgrade head`; `uv run pytest tests/unit/tui/test_assessment_view.py tests/unit/tui/test_keypress.py -v`;
  manually inspect the rendered panel in a real terminal for colored entities, the neutral
  `?` gutter on load, and the `✓`/`✗` gutter after pressing `f` on a chunk.
- **Step 7:** `uv run pytest tests/unit/preprocessing/test_annotators.py -v`; if `--extra
  assessment` is installed, `uv run python -c "import spacy; spacy.load('en_core_web_md')"`.
- **Step 8 / full pass:** `uv run mypy src/notebooklm scripts/_live_auth_scenarios
  --ignore-missing-imports && uv run pytest`.

## Risks and Open Questions

- **CI extras gap (see step 7), deferred per plan review ("let's get it working locally
  first"):** the `assessment` extra is installed by no documented command anywhere (not
  CLAUDE.md's contributor install, not CI). This goal targets a working local
  (`uv sync --extra assessment`) setup; wiring `--extra assessment` into
  `.github/workflows/test.yml` — and its coverage-gate implications per CLAUDE.md's own
  blind-spot warning — is explicitly out of scope for this pass and left for a follow-up
  decision once the local flow is proven out.
- **Transcription credential:** `DEEPGRAM_API_KEY` is already present in the user's local
  environment, so the real `TranscriptionService`/`DeepgramAdapter` path is exercisable
  locally without setup. Unit tests still mock `TranscriptionAdapter.transcribe()` rather
  than hit the real API, same pattern as the VCR-cassette approach used elsewhere in the
  repo for external calls. `TranscribeCppAdapter`'s local/offline path is explicitly
  unfinished per the plan-review comment ("still working on how to transcribe with diarize
  locally") — step 1 makes the adapter choice configurable but does not need to complete
  that path.
- **`document_id` collision risk for transcript clauses.** Step 1b keys transcript clauses by
  `artifact_id`; if `IngestionService.ingest_text` is ever called twice for the same artifact
  (e.g. re-running an assessment), `Clause.external_id` (`f"{artifact_id}:{index}"`) will
  collide with the existing unique index. `run_full_assessment` should delete-then-reinsert
  (or upsert) any existing clauses for that `document_id` before calling `ingest_text`, same
  as a re-ingested source would need. Flagging so step 1/1b's implementation doesn't skip it.
- **`FactCheckAdapter`'s external SIFT path stays a soft, always-pass fallback** (fact-8,
  explicitly out of scope for *fixing* the fallback itself): when `FACT_CHECK_FRAMEWORK_PATH`
  doesn't exist, `check()` always returns `True`. Step 6 (revised per plan review) now makes
  this visible rather than silent — a distinct `✓*` gutter glyph plus an explicit UI banner
  when `framework_available` is `False` — so the remaining risk is narrower: the *result*
  is still unverified until the separate DSPy-SIFT rebuild goal lands, but the UI no longer
  hides that fact.
