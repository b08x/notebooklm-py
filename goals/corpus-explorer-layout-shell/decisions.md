# Decisions (interview in progress)

Draft record of answers. It becomes `interview-result.json`, `facts.md`, `goal.md` and `plan.md` when the interview ends.

## Locked layout parameters (from /better-ui)

- Information density: B, structured workspace (15–40 data elements per 1440px viewport, 14px body text, 32–40px rows).
- Primary anchor: C, document view (60–70% of width, prose capped at 72ch).
- Spatial alignment: B, fluid flex, content-driven sizing, shared left edge only.
- Negative space: B, balanced working spacing (8px base unit, 24px region padding, 16px gutter with 1px divider, line-height 1.5).

## Decisions from the interview

1. Collapse breakpoint: the value lives in one variable, initial value 1024px. It is verified by eye at 1023px and 1024px. (Now superseded for the four-column layout; see item 5.)
2. Target codebase: `web/` in notebooklm-py (option A). SCC's frame, Review-screen layout and visual style are rebuilt as React components in `web/`. SCC's Dexie storage, AI provider settings and Express server are not carried over. `web/` keeps its data layer, features and tests.
3. App-level navigation: SCC's vertical sidebar replaces the header tabs (option A). 256px with labels, 64px icon-only. A toggle switches the width and the choice is saved per browser. Below 1280px the default is 64px. The header keeps breadcrumbs, the command palette trigger and the jobs tray. Screens: Review (new), Search, Browse, Map, Runs, Fact-check, then Settings.
4. Review screen list column (option A): documents grouped under collapsible "Collection" headers (expanded state saved per browser). Each card shows title, file type, clause count, and a status line (share of clauses SFL-tagged, count of clauses fact-checked). Search field plus filter tabs All / Untagged / Tagged / Fact-checked. Width 320px. A NotebookLM notebook is one kind of collection. Requires a new `/v1/corpus/documents` route.

5. Column collapse order (option A): inspector first, then list.
   - 1400px and above: sidebar (64px), list (320px), document view, inspector (≈360px) all visible.
   - 1024–1399px: inspector becomes a 360px right drawer over the document view. It opens on clause selection or from a document-header button.
   - Below 1024px: list also becomes a left drawer, opened from a header button. Sidebar stays 64px, and becomes a drawer below 768px.
   - Breakpoints are variables (1400 / 1024 / 768), checked by eye at each edge.

6. Document view content (option D, hybrid of continuous text and collapsible chunks):
   - Reading text in the 72ch column; clauses are inline spans with SFL-tag tints and verdict markers (green supported, amber unverified, red contradicted; hidden while `fact_checks` is empty).
   - Grouped by parent chunk. Each chunk has a header with its number and counts (clauses, tagged, fact-checked). Chunks are expanded by default; a header click collapses to first line plus counts.
   - Document header controls: "Collapse all" and "Collapse unflagged". Collapse state is saved per document in the browser.
   - Right-edge marker strip shows tagged and flagged clause positions; clicking it expands and scrolls to that chunk.
   - Clicking a clause selects it and fills the inspector. Arrow keys move between clauses and skip collapsed chunks.
   - Long documents are virtualized (up to 1,576 clauses).

7. Inspector (option C): 360px wide at 1400px and above, resizable 320–480px by a drag handle on its left edge (saved per browser). Header shows document title and chunk.clause number. Tabs Context / Linguistics / Similar / Raw, each scrolling inside the panel. A pinned ≈120px footer is always visible with SFL tag state, fact-check verdict, and "Tag SFL" / "Fact-check" buttons for the selected clause. Empty state: "Select a clause in the document." Below 1400px it is the right drawer from item 5.

8. Header (option A): 40px header to the right of the sidebar. Contains drawer buttons for list and inspector (visible only below their breakpoints), breadcrumbs (Collection › Document › Chunk), and the command palette trigger (Ctrl+K) at the right end. The 28px status footer and jobs tray stay unchanged. Fixed chrome: 68px.

## Still open

None. The interview is complete; next step is writing `goal.md`, `facts.md`, `interview-result.json` and `plan.md`.
- Header region presence and height.
