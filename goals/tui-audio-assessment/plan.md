# Plan — TUI Audio Overview Assessment

## Solution Approach

We will enhance the NotebookLM TUI by introducing a dedicated Audio Overview Assessment view. To support this view, we will construct a robust text preprocessing pipeline (`src/notebooklm/_preprocessing/`) that applies advanced chunking (Hybrid, Structural Coherence) and deep annotation (spaCy, Docling, BERTopic, and external fact-checking). The TUI will consume this processed context and present a side-by-side assessment interface, utilizing a hybrid LLM-assisted grading flow.

## Ordered Steps

### Step 1: Scaffold Preprocessing - Chunking Strategies
- **Files:** `src/notebooklm/_preprocessing/chunkers.py`, `tests/unit/preprocessing/test_chunkers.py`
- **Action:** Implement a `HybridChunker` class (hierarchical with tokenization-aware refinements) and a `StructuralCoherenceChunker` class (systemic functional approach).
- **Verification:** `uv run pytest tests/unit/preprocessing/test_chunkers.py` validates that text is appropriately divided while preserving functional coherence.

### Step 2: Scaffold Preprocessing - NLP & PII Annotations
- **Files:** `src/notebooklm/_preprocessing/annotators.py`, `tests/unit/preprocessing/test_annotators.py`
- **Action:** Implement `SpacyAnnotator` (POS, Lemmatization, NER), `BERTopicAnnotator` (topic modeling), and `DoclingPIIFilter` (PII removal).
- **Verification:** `uv run pytest tests/unit/preprocessing/test_annotators.py` validates that tokens are tagged, entities recognized, topics assigned, and PII masked.

### Step 3: Integrate Fact-Checking Framework
- **Files:** `src/notebooklm/_preprocessing/fact_check.py`
- **Action:** Create an adapter that utilizes the fact-checking framework located at `~/.syncopated/skills/fact-check` (`deep-background` and `sift` skills) to validate claims within the chunks.
- **Verification:** `uv run pytest tests/unit/preprocessing/test_fact_check.py` with mocked external skill calls.

### Step 4: Scaffold TUI Assessment View
- **Files:** `src/notebooklm/tui/views/assessment_view.py`, `src/notebooklm/tui/state.py`
- **Action:** Create `AssessmentView`, a dedicated fullscreen view component. Update `TUIState` to hold assessment data (audio metadata, system instructions, contextual chunks).
- **Verification:** `uv run ruff check src/notebooklm/tui/views/assessment_view.py` and `uv run mypy src/notebooklm/tui`

### Step 5: Implement Assessment Layout & Rendering
- **Files:** `src/notebooklm/tui/views/assessment_view.py`
- **Action:** Build out the Rich `Layout` for the view to display audio output metadata, original system instructions, and the annotated source chunks side-by-side.
- **Verification:** Render the view in a dummy script and verify the side-by-side layout visually or via unit tests (`tests/unit/tui/test_assessment_view.py`).

### Step 6: Implement Hybrid Grading Mechanism
- **Files:** `src/notebooklm/tui/views/assessment_view.py`, `src/notebooklm/_app/assessment.py`
- **Action:** Add UI controls (buttons/inputs) in the assessment view to display the LLM's suggested score and feedback, allowing the user to confirm or edit it. Wire it to an asynchronous LLM call.
- **Verification:** `uv run pytest tests/unit/tui/test_assessment_view.py` to ensure grading events trigger state updates.

### Step 7: Wire Assessment View into TUI Routing
- **Files:** `src/notebooklm/tui/app.py`, `src/notebooklm/tui/keypress.py`, `src/notebooklm/tui/layout.py`
- **Action:** Add a keybinding (e.g., `A` or `:assess`) in `keypress.py` to toggle the fullscreen `AssessmentView`. Update `app.py` and `layout.py` to mount/unmount this view when active.
- **Verification:** `uv run pytest tests/unit/tui/test_keypress.py` and manually run `notebooklm tui` to verify the view opens correctly.

## Risks & Open Questions

- **Dependency weight:** Introducing `spacy`, `bertopic`, and `docling` will significantly increase the dependency footprint. We need to ensure these are placed behind an `[extra]` flag (e.g., `uv pip install notebooklm-py[assessment]`) so the base CLI remains lightweight.
- **Fact-Check Framework Integration:** Relying on `~/.syncopated/skills/fact-check` means depending on a local file path. We should make this path configurable via environment variables or settings so it doesn't break in different environments.
- **Performance:** Running heavy NLP pipelines and topic modeling synchronously will block the UI. These must be dispatched to background tasks (already supported by TUIState `background_task`).
