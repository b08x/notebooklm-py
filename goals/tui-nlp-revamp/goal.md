# TUI NLP Revamp

## Goal
Revamp the current NotebookLM TUI (`notebooklm.tui`) to adapt to a traditional NLP analysis UX design. We will transition from the existing two-pane layout to a three-pane layout featuring a document tree, results list, and detail view, ensuring all current command and notebook functionalities are fully supported.

## Shared Understanding
The specific requirements and facts dictating this work are tracked in [facts.md](facts.md).

## Execution Plan
The step-by-step approach to migrating the layout and validating the changes is tracked in [plan.md](plan.md).

## Done Condition
This goal is considered done when the `notebooklm.tui` runs locally with the new three-pane design, correctly displaying the hierarchical notebook tree, mapping existing command flows into the new pane structure, and functioning without layout breaks or regressions in current TUI capabilities.
