# TUI Data Storytelling Plan

## Solution Approach
We will rewrite `AssessmentView.render()` in `src/notebooklm/tui/views/assessment_view.py` to use a nested Rich `Layout` instead of a flat `Group` when the assessment is active. This layout will divide the screen into three semantic regions: header stats (top), active claim (bottom-left), and log stream (bottom-right). We will replace simple ASCII progress bars with custom block-character sparklines for a denser data display. The log stream will be transformed into a `rich.tree.Tree` to show the hierarchy of claims and their citations. Finally, we'll enforce the restrained aesthetic by replacing hardcoded colors with semantic theme colors (e.g., `success`, `error`) and using `box.ROUNDED` for all panels.

## Ordered Steps
1. **Layout Restructuring**: Inside `AssessmentView.render()`, instantiate a `Layout()` named `assessment_dash`. Split it into a `header` layout and a `body` layout, then split `body` row-wise into `claim_pane` and `log_pane`.
2. **Sparkline Implementation**: Create a `make_sparkline(pct, width)` helper using fractional block characters (` ▂▃▄▅▆▇█`) for progress and accuracy. Apply semantic theme colors (`success`, `primary`) instead of hardcoded ansi colors. Update the header stats table to use these sparklines.
3. **Tree-based Log Stream**: Replace the flat `Group` of `Text` elements for the log stream with `rich.tree.Tree`. For each item in `ticker_stream`, add a root node for the claim (with status icons), and add citations as child nodes to that tree.
4. **Aesthetic Enhancements**: Wrap the regions in `Panel`s using `box.ROUNDED` and semantic `border_style` (e.g. `primary`, `muted`). Apply deep padding (e.g. `padding=(1, 2)`) for concentric spacing.
5. **Integration**: Return `assessment_dash` as the first renderable, leaving the second empty, replacing the old `loading_panel`.

## Verification
- **Step 1**: Render the TUI and start an assessment. Verify the 3-pane layout appears correctly proportioned.
- **Step 2**: Check that the sparkline renders smoothly using block characters.
- **Step 3**: Verify the log stream displays as a hierarchical tree structure with citations nested under claims.
- **Step 4 & 5**: Visual check for rounded corners and consistent semantic colors matching `theme.py` without hardcoded colors.

## Risks
- **Nested Layout Constraints**: A `Layout` inside a `Panel` inside another `Layout` (from `app.py`) might have height calculation quirks. If rendering breaks, we will return the `assessment_dash` Layout directly instead of wrapping it in a parent Panel.
