# Goal (stub) — Regenerate artifacts from compiler templates

Status: stub. Run /plannotator-setup-goal to expand it.

When an artifact is recorded as `not_downloadable` (failed or incomplete) in a notebook-curation archive manifest, regenerate it in NotebookLM from a compiler YAML project (`examples/notebooklm-{audio,video}/projects/*.yaml` via `src/notebooklm/tui/compiler_bridge.py`), then download it.

Origin: plan review of goals/notebook-curation (2026-09-29). Depends on notebook-curation fact 20 (the manifest records artifact kind, status, and generation prompt).

Evidence: [prompt-survey-2026-09-29.txt](prompt-survey-2026-09-29.txt), per-month × kind counts of artifacts with and without generation_prompt. Match mind maps and flashcards by kind, because they almost never carry a prompt.
