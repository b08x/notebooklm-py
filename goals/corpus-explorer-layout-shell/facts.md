# Facts

## Shell and navigation
- The app shell is a flex row: a left sidebar, then a column containing a 40px header, the screen content, and the 28px status footer.
- The sidebar lists these screens in order: Review, Search, Browse, Map, Runs, Fact-check, then Settings; the header no longer contains navigation tabs.
- The sidebar is 256px wide with labels or 64px wide with icons only; a toggle button switches between them and the choice persists across reloads in the same browser.
- Below a viewport width of 1280px the sidebar defaults to 64px when no stored choice exists.
- Below a viewport width of 768px the sidebar becomes a drawer opened from a header button.
- The header is 40px high and contains the list-drawer and inspector-drawer buttons (visible only below their breakpoints), breadcrumbs, and the command palette trigger at the right end.
- The 28px status footer and its jobs tray are unchanged.
- The breakpoints 1400px, 1024px and 768px are defined in one place as named constants.

## Review screen layout
- The Review screen shows four regions left to right: sidebar, document list (320px), document view, inspector.
- At a viewport width of 1400px or more all four regions are visible at once.
- Between 1024px and 1399px the inspector is a 360px drawer that slides in from the right over the document view; it opens when a clause is selected or when the header button is pressed.
- Below 1024px the document list is also a drawer, sliding in from the left and opened from a header button; choosing a document closes it.
- Drawers close on Escape and on a click outside, and keep keyboard focus inside while open.
- The document view takes the remaining width, has `min-width: 0`, and scrolls on its own; the page itself does not scroll.
- Prose in the document view is capped at 72ch and starts at the shared left edge; tables, code blocks and figures may extend to the full width of the region.
- Spacing follows an 8px base unit: region padding 24px, gutter between regions 16px with a 1px divider, body line-height 1.5, 24–32px between sections, 8–12px between related elements.
- Body text is 14px and list rows are 32–40px high.

## Document list
- The list groups documents under collapsible group headers labeled "Collection"; a NotebookLM notebook is one kind of collection, and the interface never says "Notebook" in the group header.
- Each group header shows the collection title and its document count; the expanded or collapsed state of each group persists in the browser.
- Each document card shows title, file type (md, pdf, csv, png, transcript), clause count, and a status line with the share of SFL-tagged clauses and the count of fact-checked clauses.
- A search field above the list filters documents by title as the user types.
- Filter tabs All, Untagged, Tagged and Fact-checked narrow the list.
- A new endpoint `GET /v1/corpus/documents` returns the documents with collection id and title, file type, clause count, tagged count and fact-checked count; it works without a signed-in NotebookLM client.
- Selecting a document shows it in the document view and adds the document to the URL.

## Document view
- The document view shows the selected document as reading text grouped by parent chunk, each chunk preceded by a header with its number and its counts of clauses, tagged clauses and fact-checked clauses.
- Clauses are inline spans; an SFL-tagged clause has a background tint.
- A fact-checked clause has a line-start marker: green for supported, amber for unverified, red for contradicted; no marker appears for a clause without a fact check.
- Chunks are expanded by default; a click on a chunk header collapses it to its first line plus its counts.
- The document header has "Collapse all" and "Collapse unflagged" controls, and collapse state persists per document in the browser.
- A strip along the right edge of the view marks the positions of tagged and flagged clauses; clicking a position expands that chunk and scrolls to it.
- Clicking a clause selects it and fills the inspector; the Up and Down arrow keys move to the previous and next clause and skip clauses inside collapsed chunks.
- A document of 1,576 clauses renders and scrolls without visible delay, because only visible rows are mounted.

## Inspector
- The inspector is 360px wide at 1400px or more, can be resized between 320px and 480px with a handle on its left edge, and the width persists in the browser.
- Its header shows the document title and the chunk and clause number.
- Its tabs are Context, Linguistics, Similar and Raw, each scrolling inside the panel.
- A footer of about 120px stays visible under every tab and shows the SFL tag state and fact-check verdict of the selected clause with "Tag SFL" and "Fact-check" buttons.
- With no clause selected the inspector shows "Select a clause in the document."

## Preserved behavior
- The Search, Browse, Map, Runs and Fact-check screens keep their current features, URL parameters and tests, and appear under the new sidebar.
- The URL encodes the active screen, document and selected clause, and reloading restores that view; Back and Forward move between screens and selected documents.
- The breadcrumbs show Collection › Document › Chunk using titles, not UUIDs.
- New controls use the existing color tokens, transitions of 150ms or less on named properties, and scale 0.96 on press.
- Vitest, Playwright, mypy, and the CI-equivalent pytest command pass, and the rebuilt bundle is committed on `development`.
- Each breakpoint (1400px, 1024px, 768px) is checked by eye at one pixel above and one pixel below its value, and the result is recorded in `verification.md`.
