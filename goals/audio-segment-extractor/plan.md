# Plan — Audio Segment Extractor (v1, ~2h budget)

## Approach

A new uv package `audioseg` at `~/WorkspaceV3/audio-segment-extractor`. Pure-Python core (parse → model → export plan) with no Textual imports, so it is tested directly; a thin Textual layer on top; in-process playback via `sounddevice`. No `notebooklm` import, no DB, no network (facts 1–2). Data contract = files on disk: audio + `*_diarization.json`.

```
audio-segment-extractor/
  pyproject.toml            textual, pydub, sounddevice, numpy; dev: pytest, pytest-asyncio
  src/audioseg/
    model.py      Sentence(idx, turn_idx, speaker, start_ms, end_ms, text), Turn(idx, speaker, sentences)
    parse.py      load_diarization(path) -> list[Turn]; format detection + 3 parsers
    discover.py   find_pairs(root) -> list[Pair(json, audio)] newest first
    export.py     plan_export(...) -> list[OutputFile]; write_sidecar(...); run_export(audio, plan)
    player.py     Player.play(audio_segment, start_ms, end_ms) / stop(); PlaybackError
    app.py        AudiosegApp, PickerScreen, EditorScreen, ExportScreen (modal)
    cli.py        `audioseg [--root DIR] [AUDIO JSON]`
  tests/
    fixtures/deepgram.json, assemblyai.json, speechmatics.json (small synthetic, 2 speakers, ~6 sentences)
    test_parse.py, test_discover.py, test_export.py, test_app.py (Pilot)
```

Key map (EditorScreen): `j/k`/arrows move · `space` toggle sentence · `t` toggle turn · `/` search · `esc` clear search · `f` speaker filter · `p` play/stop · `tab` focus selection panel · `[`/`]` move selected clip up/down (in panel) · `e` export · `q` quit.

## Steps

### 1. Scaffold package (~10 min) — facts 1, 2, 20
- `uv init --package --lib audio-segment-extractor` in `~/WorkspaceV3`; set name `audioseg`, `[project.scripts] audioseg = "audioseg.cli:main"`; add deps.
- **Verify:** `uv run audioseg --help` exits 0; `grep -rn "notebooklm\|httpx\|requests" src/` returns nothing (becomes `test_no_notebooklm_import` asserting `sys.modules` after importing `audioseg.app` has no `notebooklm*`).

### 2. Model + parsers (~25 min) — facts 5, 6
- Port `parse_diarization` logic from `scripts/extract_sentences.py` into three functions producing `list[Turn]`.
- Deepgram: if `alternatives[0].paragraphs.paragraphs[*].sentences` exist, use them (paragraph carries `speaker`); else group `words` by speaker and split on `.?!` terminal `punctuated_word`.
- AssemblyAI (list of utterances, ms): split each utterance's `words` on terminal punctuation; if no `words`, one sentence = the utterance.
- Speechmatics: word/punctuation entries; group by speaker, split at `punctuation` entries whose content is `.?!`.
- Turns = consecutive same-speaker runs; sentence times in ms.
- **Verify:** `uv run pytest tests/test_parse.py` — per fixture: turn count, speakers, sentence count, first/last sentence start/end/text; plus a smoke test against the real Deepgram file under `~/NotebookLM` (skipped if absent) asserting ≥1 turn and sentences ordered by start.

### 3. Discovery + CLI (~10 min) — facts 3, 4
- `find_pairs(root)`: rglob `*_diarization.json`; audio = sibling with same stem minus suffix and extension in {wav, mp3, m4a, flac, ogg, mp4}; sort by JSON mtime desc; JSON without audio is skipped.
- CLI: two positional args → open EditorScreen directly; none → PickerScreen; `--root` default `~/NotebookLM`.
- **Verify:** `tests/test_discover.py` with `tmp_path` (paired, unpaired, UUID-named, mtime ordering); Pilot test that `AudiosegApp(audio=…, json=…)` starts on EditorScreen.

### 4. Export core (~20 min) — facts 16, 17, 18
- `plan_export(clips, mode, fmt, out_path)` pure: combined → one OutputFile with all clips in order; separate → `<stem>_<NNN>_<speaker>.<fmt>`, NNN = 1-based export position.
- `write_sidecar(plan, source_audio, source_json)` → `<out_stem>.json`: `{source_audio, source_json, format, mode, clips:[{position, speaker, start_ms, end_ms, text, output_file}]}`.
- `run_export` slices the pydub `AudioSegment` and exports with `format=fmt`.
- **Verify:** `tests/test_export.py` — plan naming/order for both modes; sidecar content; real write of wav/flac from a generated 3 s sine `AudioSegment` and check durations (±5 ms); mp3 test skipped if ffmpeg missing.

### 5. Player (~10 min) — facts 13, 14
- `Player` holds decoded samples (numpy from pydub, loaded once in a Textual worker); `play()` calls `sd.stop()` then `sd.play(slice, sr)` (non-blocking); `toggle` = stop if playing the same idx. Any `sd.PortAudioError`/`OSError` → `PlaybackError`.
- **Verify:** unit test with `sounddevice.play` monkeypatched to raise → Pilot asserts a notification is shown and app is still running (fact 14). Audible playback = manual (fact 13).

### 6. Textual UI (~35 min) — facts 7–12, 15
- EditorScreen: `DataTable` (cursor_type=row) with turn header rows (`── Speaker 0 · 0:00–0:42 ──`) and sentence rows `[✓] | spk | start | end | dur | text`; header rows are skipped by `space` but targeted by `t`.
- State lives in a plain `Session` object (selected set, export order list, speaker filter set, search text); table re-renders from `Session.visible_rows()` — filtering never touches `selected` (fact 11).
- Status bar: `N clips · M:SS selected` recomputed on every change (fact 10).
- Search: `Input` docked bottom, hidden until `/`; `esc` clears and hides (fact 12).
- Speaker filter: modal with `SelectionList` of speakers.
- Right panel: `ListView` of selected clips in export order; new selections insert chronologically; `[`/`]` swap (fact 15).
- ExportScreen modal: `RadioSet` combined/separate, `Select` wav/mp3/flac, `Input` path (default `<audio_dir>/<audio_stem>_clips.<fmt>`); runs export in a worker, notifies result.
- **Verify:** `tests/test_app.py` Pilot: load deepgram fixture → assert header+sentence rows; `space` → status shows 1 clip + correct duration; `t` on a turn selects all its sentences; `/` type text → row count shrinks, `esc` restores; filter out a speaker → rows hidden, status count unchanged; `[` reorders panel; export (separate, wav, tmp_path) → files + sidecar exist with expected order (fact 19).

### 7. Manual pass + cleanup (~10 min) — facts 13, 20, 21
- Run `uv run audioseg` on the real `Stop AI hallucinations…` pair: pick, preview, select 3 sentences across turns, reorder, export combined mp3 + separate wav; play outputs with mpv.
- Run once over `ssh localhost` to confirm terminal rendering.
- Delete `scripts/extract_sentences.py` from notebooklm-py and commit (no other references exist; `questionary`/`pydub` deps in notebooklm-py's pyproject stay — other uses not audited, out of scope).
- **Verify:** `git -C ~/WorkspaceV3/notebooklm-py status` shows the deletion; full `uv run pytest` in audioseg green.

### 8. Optional (only if time remains) — fact 22
- In notebooklm TUI, a key (e.g. `x` in notebook detail) sets a flag; `app.py`'s existing `live.stop()` / `suspend_raw_terminal()` / `live.start()` handoff (used for `$EDITOR`) runs `subprocess.run(["audioseg", "--root", <notebook assets dir>])`.
- **Verify:** manual.

## Risks / open questions
- **Sentence splitting quality** for non-Deepgram formats is heuristic (abbreviations like "e.g." split). Acceptable for v1; only Deepgram files exist locally, so AssemblyAI/Speechmatics are exercised by synthetic fixtures only.
- **Memory:** a 22-min WAV decodes to ~230 MB float32 stereo; fine locally. Load once in a worker so the UI does not block.
- **sounddevice over SSH** plays on the host machine, not the SSH client; this is expected, but preview is not useful remotely.
- **DataTable + header rows:** selection keys must ignore header rows; row keys encode `h:<turn>` vs `s:<idx>` to disambiguate.
- **Budget:** steps 1–7 ≈ 2h. If behind, drop step 8 first, then the speaker-filter modal (replace with a single-key cycle).
