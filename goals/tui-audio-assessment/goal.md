# Goal — TUI Audio Overview Assessment

## Articulated Goal

Enhance the NotebookLM TUI to support assessing audio overviews against their system instructions. This involves building a robust text preprocessing pipeline—integrating Hybrid chunking, Structural Coherence chunking, and advanced NLP annotation modules (spaCy, Docling, BERTopic, and a fact-checking framework)—to contextualize the background source material used for the audio generation, effectively "putting all the bells and whistles into it."

## Reference

- **Facts:** `goals/tui-audio-assessment/facts.md` — 8 accepted facts defining the assessment view, hybrid chunking and coherence strategies, NLP annotations (spaCy, Docling, BERTopic, fact-checking), and a hybrid grading model.
- **Plan:** `goals/tui-audio-assessment/plan.md` — 7-step execution plan covering preprocessing scaffolding, annotators, fact-checking integration, assessment view rendering, grading logic, and TUI routing.

## Done Condition

- `notebooklm tui` provides access to the Audio Overview Assessment view.
- The preprocessing pipeline successfully chunks text using Hybrid and Structural Coherence methods.
- Source chunks are annotated using spaCy, Docling (PII removal), BERTopic, and the external `~/.syncopated/skills/fact-check` framework.
- The TUI displays audio generation outputs, system instructions, and contextualized source chunks side-by-side.
- The assessment view allows users to review an LLM-suggested score/feedback and confirm or edit it.
- Heavy NLP dependencies are placed behind an optional installation flag (e.g., `[assessment]`).
- All unit tests for chunkers, annotators, and the new TUI components pass successfully.
