# Facts

- When the user triggers assessment (the 'a' key / start_assess_audio_overview path), the system checks whether an audio overview exists AND whether ingested source clauses exist for the notebook.
- If an audio overview artifact exists, assessment runs over the audio transcript chunks using the existing run_full_assessment() pipeline (unchanged behavior).
- If no audio overview exists but ingested source clauses are present in the database, assessment runs over the source clauses using a new run_source_assessment() function.
- run_source_assessment() loads already-ingested Clause rows from the database for the given notebook (keyed by source IDs), without re-chunking or re-ingesting anything.
- run_source_assessment() runs each loaded clause through the same SFL analysis, claim detection, and HITL fact-check loop that run_full_assessment() uses — speaker-diarization logic is skipped since sources have no speaker turns.
- run_source_assessment() returns an AssessmentResult with system_instructions populated from the notebook AI summary (resolve_notebook_context, empty string if unavailable).
- run_source_assessment() returns an AssessmentResult with audio_metadata populated as a JSON blob containing the assessed source IDs, source count, and a 'mode' key set to 'sources' to distinguish it from audio runs.
- If neither audio overview nor ingested source clauses are available when assessment is triggered, the system shows an error message ('No assessable content found — generate an audio overview or ingest sources first.') and does not change the current view.
- The assessment_state dict produced by source-assess includes 'assessment_mode': 'sources' so the TUI can label the view appropriately (e.g. 'Source Assessment' vs 'Audio Assessment').
- Unit tests are added for run_source_assessment() covering: happy path (clauses present → AssessmentResult returned), and no-sources case (empty clauses → raises or returns error signal).
- The existing run_full_assessment() function and its audio-based path remain unchanged in behavior. API call footprint must stay low — prefer deterministic local paths; when LLM is required use low-cost OpenRouter models (gemma4, phi-4, deepseek-flash-v4).
