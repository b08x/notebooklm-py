# Goal: TUI Data Storytelling Redesign

Overhaul the visual layout of the NotebookLM Terminal User Interface (TUI) to reduce cognitive load and improve intuitive navigation. By leveraging Rich's Layout, Tree, and Text capabilities, we will transform the assessment view into a multi-pane dashboard that presents progress and evidence through effective data storytelling.

## Specifications
- **Shared Understanding**: See [facts.md](facts.md) for the agreed-upon design elements and visual aesthetics.
- **Execution Plan**: See [plan.md](plan.md) for the step-by-step implementation approach.

## Done Condition
- `AssessmentView.render()` returns a nested `Layout` with three distinct regions (header stats, active claim, log stream).
- Progress and accuracy are visualized with block-character sparklines.
- The evidence log stream is rendered as a hierarchical `Tree`.
- All styling uses semantic theme colors and rounded borders.
