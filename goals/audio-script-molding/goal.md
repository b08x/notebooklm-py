# Goal (stub): Audio script molding (transcript → edited script → local TTS)

Status: stub. Decisions from the 2026-09-29 grilling session are recorded below. Run /plannotator-setup-goal to expand it. Depends on goals/audio-compiler-generation.

## Pipeline
NotebookLM generates the draft audio overview (from a compiler template) → diarized transcription → turn-segmented script → manual edits → re-rendered by local TTS with a fixed voice per persona. The voice map, not NotebookLM's voice assignment, keeps the voices consistent.

## Decided
- **Edit surface (Q2 = A):** Markdown script file edited in `$EDITOR`, stored in the Obsidian vault at `~/Notebook/NotebookLM/Scripts/<project-slug>/<YYYYMMDD>-<notebook-slug>/`.
  - `raw.md` is the diarized transcript as generated and is never edited.
  - `script.md` is the editable copy. Each turn is a block: `### T012 · Mrs (00:03:41)`. Frontmatter holds project, notebook id, artifact id, template, the speaker→persona map (e.g. `{A: Mrs, B: Mr}`), and the voice map.
  - Audio binaries are stored in `~/Archive/NotebookLM/audio/`, outside the vault, and linked from the frontmatter.
- **Segmentation (Q3 = A):** consecutive fragments from the same speaker are merged. Backchannels are classified linguistically: a fragment is a backchannel when every non-punctuation token is a spaCy INTJ (`_preprocessing/sfl_engine.py`, en_core_web_md) or a Deepgram-tagged filler (`filler_words=true`). Duration is the fallback for fragments that cannot be classified. A backchannel becomes an inline `[bc: …]` marker in the surrounding turn, and TTS drops markers by default (per-project flag to render them). Inline fillers (um/uh) are kept in raw.md and removed from script.md by default (flag to keep).
- **Rendering (Q4 = A):** one TTS clip per turn, cached by hash(text + voice + backend + speed). Clips are joined with a configurable gap (default 250 ms, shorter at `[bc:]` sites) into final.mp3. The same per-turn method is used for both backends so they can be compared.
  - Primary backend: supertonic-api (`~/LLMOS/supertonic-api`), an OpenAI-compatible endpoint `POST /v1/audio/speech` on :8800 (:8801 via compose). 4096-character limit per request. Female voices F1–F5 (alloy, nova, shimmer, ash, coral), male voices M1–M4 (echo, fable, onyx, cedar).
  - Secondary backend: ElevenLabs, for a few comparison examples. Its text-to-dialogue endpoint is deferred.

## Open
- Whether "highly refined language parser" means the in-repo spaCy/SFL code or the standalone SFL package.
- Which diarization provider is the default (Deepgram, AssemblyAI, or Speechmatics).
