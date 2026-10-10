# Corpus Explorer — Verification

Run on 2026-10-10 against Postgres 16 + pgvector on :5435 and Redis 7.

## Gates

| Command | Result |
|---|---|
| `uv run ruff check .` / `uv run ruff format --check .` | exit 0 |
| `uv run mypy src/notebooklm scripts/_live_auth_scenarios --ignore-missing-imports` | exit 0 (455 files) |
| `uv run pytest -n auto --dist loadgroup --cov=src/notebooklm --cov-fail-under=90` | exit 0 — 17,362 passed, 65 skipped, 93.04% coverage |
| `pnpm -C web test` | exit 0 — 67 Vitest tests |
| `pnpm -C web build` | exit 0 — writes `src/notebooklm/server/static/ui` |
| `pnpm -C web exec playwright test` | exit 0 — 3 tests |

## Facts

`[auto]` facts name the automated checks. `[manual]` facts were checked by hand
in Chromium against `notebooklm-server` (6,017 seeded chunks).

| Fact | Evidence |
|---|---|
| 1 | `tests/server/test_corpus_routes.py::test_ui_is_served_with_spa_fallback`, `test_real_app_mounts_ui_publicly`; Playwright "the UI loads at /ui" |
| 2 | `test_every_corpus_route_requires_token` (all 29 `/v1/corpus` route/method pairs → 401) |
| 3 | manual: token entered once, absent after reload; `App.test.tsx` "asks for the token once and keeps it" |
| 4 | `test_database_unreachable_is_503`; `App.test.tsx` "an unreachable database blocks the UI" |
| 5 | `web/src/test/stack.test.ts`; Playwright loads the built app from `/ui` |
| 6 | manual: header tabs, filters / results / detail panes, status footer (screenshots) |
| 7 | manual: dark default, body `rgb(24,24,27)`, `--primary #a78bfa`, `--secondary #7dd3fc`; light choice persists across reload |
| 8 | manual: `transition-duration: 0s` during the switch frame, restored after; `lib.test.ts` theme test |
| 9 | `App.test.tsx` footer test; Playwright footer check |
| 10 | `test_hybrid_search_reports_leg_ranks`; `SearchResults.test.tsx` score bars |
| 11 | `test_search_modes`; `Workbench.test.tsx` mode toggle |
| 12 | `SearchResults.test.tsx` highlight; Playwright `mark` check |
| 13 | `test_embedder_down_degrades_to_keyword`; `SearchResults.test.tsx` warning |
| 14 | `test_concurrent_searches_never_configure_dspy`, `test_corpus_explorer_module_is_llm_free` |
| 15 | manual: 6,017 chunks loaded by keyset pages, ≤45 rows in the DOM, ~62 frames/s while scrolling; `BrowseTable.test.tsx` |
| 16, 17 | `test_filters_and_facets`, `tests/unit/app/test_noise.py`; `FiltersPane.test.tsx` |
| 18 | `test_chunk_detail`; `DetailPane.test.tsx` child highlight |
| 19, 20 | `test_neighbors_and_near_duplicates`; `DetailPane.test.tsx` neighbours |
| 21, 22 | `tests/unit/app/test_corpus_mutations.py`; `DetailPane.test.tsx` four-level menu |
| 23 | `test_delete_preview_then_confirm`; `DeleteDialog.test.tsx`; Playwright Cancel/Confirm |
| 24 | `useHotkeys.test.tsx` (x, shift-x range); `Views.test.tsx` bulk bar |
| 25 | `test_export_markdown_and_json`, `test_export_and_note`; `Views.test.tsx` download |
| 26 | route + fake-client tests (`test_export_to_note_per_notebook`, `test_export_and_note`). Manual: without a NotebookLM login the app reports "run notebooklm login" and stays signed in; a real push needs NotebookLM credentials, not available here |
| 27 | `test_answer_notebooklm_scopes_sources_and_maps_citations`, `test_answer_notebooklm_scoped_with_citations` |
| 28 | `Answer.test.tsx`, `AskDrawer.test.tsx` |
| 29 | `test_answer_litellm_streams_tokens`, `test_answer_model_streams_over_sse`; `AskDrawer.test.tsx` |
| 30 | manual: "NotebookLM is answering · 1s" shown while the answer is pending; `AskDrawer.test.tsx` |
| 31 | `test_map_points_color_by_document_then_topic`; Playwright map click |
| 32 | `test_runs_stats_and_new_count`; `Views.test.tsx` runs |
| 33 | `test_runs_stats_and_new_count` (new-since); `Workbench.test.tsx` 5 s poll + pill |
| 34–39 | `tests/unit/app/test_factcheck_runs.py`, `tests/server/test_factcheck_routes.py` (live SSE, tab closed, replay); `FactCheck.test.tsx` |
| 40 | `tests/unit/tui/jobs/test_handler_fact_check.py`, `tests/unit/tui/test_assessment_gate_keys.py` |
| 41, 42 | `CommandPalette.test.tsx`, `useHotkeys.test.tsx` |
| 43 | `tests/unit/test_sfl_format.py`, `test_sfl_panel_shows_nested_tenor_values_not_keys` |
| 44 | `stack.test.ts` (no `transition: all`, buttons `active:scale-[0.96]`) |
| 45 | `/v1/corpus` route tests use the real Postgres; the seed step errors (not skips) when it is down |
| 46 | Vitest: search results, detail pane, undo toast, fact-check gate, command palette |
| 47 | Playwright smoke |
| 48 | gates above |
| 49, 50 | `tests/unit/app/test_scope.py`, `test_sfl_run_for_document_scope`, `test_auto_skip_pause_cancel`; `DetailPane.test.tsx` Assess menu |
| 51–56 | `tests/unit/app/test_artifact_ingest.py`, `tests/unit/preprocessing/test_audio_prep.py`, `test_artifact_list_and_ingest_job`; `IngestDialog.test.tsx` |
| 57 | `test_transcription_options_and_providers`, `test_providers_with_key_status`; `IngestDialog.test.tsx` |
| 58, 59 | `test_jev_gate_probability_and_context`, `test_compare_gates_*`; `FactCheck.test.tsx` gate card |
| 60, 61 | `tests/unit/app/test_corpus_answer.py` (real `dspy.ReAct` + `MultiChainComparison` on `DummyLM`; RLM sandbox error); `test_answer_auto_picks_agent_across_notebooks`, `test_answer_deep_unavailable_and_no_hits` |
| 62 | `test_neighbors_and_near_duplicates` (browse filter); `FiltersPane.test.tsx` |
| 63 | `test_llm_configured_only_on_main_thread`, `test_answer_corpus_real_react_and_mcc` (asserts no `dspy.configure`) |

## UI review (`web/`)

The `/better-ui` skill is not installed in this environment, so the review was
done by hand against the plan's better-ui rules and the mockups:

- Press: every button primitive, tab, radio, toggle and small text button scales
  to 0.96 on press; full-width list rows use a pressed background instead.
- Transitions: every transition names its properties; none uses `all`
  (enforced by `stack.test.ts`).
- Radii: segmented controls and nested surfaces are concentric (8 px outer,
  2 px padding, 6 px inner); dialogs 12 px around 8 px controls.
- Motion: icon swaps (theme, Pause/Resume) cross-fade at scale 0.25→1,
  opacity 0→1, blur 4 px→0; `AnimatePresence initial={false}` throughout;
  `prefers-reduced-motion` honoured; theme switches suppress transitions.
- Fixed during review: panel overflow from the map canvas and unbreakable
  base64 text, the detail action bar clipping, the elapsed timer resetting at
  finish, SIFT steps reading "pending" for chunks that never ran SIFT, and a
  NotebookLM-auth 401 signing the user out.

Verdict: **Approve**.
