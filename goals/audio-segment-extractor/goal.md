# Goal — Audio Segment Extractor (v1)

Replace the prompt-driven `scripts/extract_sentences.py` with `audioseg`, a standalone Textual terminal app at `~/WorkspaceV3/audio-segment-extractor`. It reads an audio file and its diarization JSON, shows a searchable, speaker-filterable transcript at sentence level grouped by speaker turn, previews audio in-process, and exports the selected clips in a reorderable order as one combined file or as separate files, each export with a JSON sidecar. It does not import the notebooklm package, read its database, or make network calls.

- **Shared understanding:** [facts.md](facts.md) (22 accepted facts; 3 are checked manually)
- **Execution plan:** [plan.md](plan.md) (approved; steps 1–7 core, step 8 optional)

## Done when

- `uv run pytest` passes in `~/WorkspaceV3/audio-segment-extractor`, covering every fact marked for automated checking (parsers for all three formats, discovery, export plan and sidecar, and the Pilot flow select → reorder → export).
- A manual run on the real `Stop AI hallucinations with logic and personas` pair previews audio and produces correct combined and separate exports with sidecars.
- `scripts/extract_sentences.py` is deleted from notebooklm-py.
- Step 8 (a launch key in the notebooklm TUI) is done or recorded as deferred.

## Status (2026-09-30)

- `~/WorkspaceV3/audio-segment-extractor` built; `uv run pytest` green (26 tests): parsers for all three formats (paragraph + word fallback for Deepgram), discovery, export plan/sidecar/duration, and the Pilot select → reorder → export flow.
- Real pair (`Stop AI hallucinations with logic and personas`) validated headlessly: 177 turns / 354 sentences parsed; combined mp3 duration exact (7440 ms); separate wavs + sidecar verified via ffprobe (`scripts/real_pair_check.py`).
- `scripts/extract_sentences.py` deleted from notebooklm-py (commit `750b005f`).
- Step 8 **deferred** (optional; no TUI launch key added).
- Still manual (needs a human at the terminal): in-app `p` preview audibility, interactive run over SSH, and playing the exported files with mpv.
