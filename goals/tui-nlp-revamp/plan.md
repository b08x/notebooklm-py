# Plan: TUI NLP Revamp

## Solution Approach
We will refactor the existing two-pane `rich` layout into a traditional three-pane NLP/IDE layout (Sidebar, Results List, Document Detail). To ensure all existing commands and notebook uses are preserved, we will map the current state views (`NOTEBOOK_LIST`, `NOTEBOOK_DETAIL`, `CHAT`, `COMPILER`) into this new 3-pane architecture. The Sidebar will evolve into a Tree view displaying notebooks and sources, while the content area splits into a top "Results/List" pane and a bottom "Detail/Action" pane.

## Ordered Steps

1. **Mockup Generation & Validation**
   - Created a functional layout mockup script (`goals/tui-nlp-revamp/mockup.py`) to visualize the structural changes (Tree sidebar, Top Results list, Bottom Detail view, Input footer).
   - *Verification: Mockup is complete and can be run by the user for visual inspection.*

2. **Refactor `layout.py`**
   - Update `build_layout` to split the `body` into `sidebar` (ratio=1) and `content` (ratio=3).
   - Split `content` vertically into `results` (ratio=1) and `detail` (ratio=1) as validated by the mockup.
   - Files touched: `src/notebooklm/tui/layout.py`

3. **Adapt `app.py` for 3-Pane Rendering**
   - Modify `update_layout` to update `layout["sidebar"]`, `layout["content"]["results"]`, and `layout["content"]["detail"]` instead of the old `sidebar["notebooks"]`, `sidebar["commands"]`, and `main`.
   - Files touched: `src/notebooklm/tui/app.py`

4. **Enhance Sidebar Renderer with Tree View**
   - Update `render_sidebar_notebooks` to use a `rich.tree.Tree` instead of a `Table` for the primary document hierarchy.
   - Integrate the commands (from `render_sidebar_commands`) into the bottom of the sidebar tree.
   - Files touched: `src/notebooklm/tui/renderers/sidebar.py`

5. **Split and Update Main Renderers**
   - Refactor `render_main` to yield two panels: one for the `results` pane and one for the `detail` pane.
   - *Notebook List / Detail Views*: `results` shows the notebook list/actions; `detail` shows the summary or metadata.
   - *Chat / Compiler Views*: Map the conversation history/results to the `results` pane and the current input/compilation output to the `detail` pane.
   - Files touched: `src/notebooklm/tui/renderers/main.py`, `src/notebooklm/tui/renderers/chat.py`, `src/notebooklm/tui/renderers/compiler.py`

6. **Test and Verify Keybindings**
   - Ensure `state.py` and `keypress.py` correctly navigate focus between the three panes or ensure the existing global shortcuts still logically apply to the new layout structure.
   - Files touched: `src/notebooklm/tui/keypress.py`, `src/notebooklm/tui/state.py`

## Verification for Each Step
- **Step 1:** Run `python goals/tui-nlp-revamp/mockup.py`
- **Step 2 & 3:** Run `python -m notebooklm.tui` and verify the screen is divided into the 3 correct pane areas.
- **Step 4:** Visually confirm the Notebooks appear in a hierarchical Tree structure and actions are visible.
- **Step 5:** Navigate to a Notebook Detail, Chat, and Compiler view. Verify no UI elements or functionalities from the old `main.py` are missing.
- **Step 6:** Press `[Enter]`, `[c]`, `[p]`, `[s]`, `[r]`, `[q]` and ensure they all trigger their respective state changes without layout crashes.

## Risks and Open Questions
- **Pane Focus:** The current TUI might not have an explicit concept of "focused pane" since it's mostly global keybinds. We may need to add a focus state to `TUIState` if we want the user to scroll the results vs the detail pane independently.
- **Terminal Size:** A 3-pane layout requires more terminal real estate. On smaller terminals, text may wrap unpleasantly, as seen in the mockup's sidebar. We might need minimum size checks or responsive hiding of the sidebar.
