# Facts — NotebookLM TUI

1. The TUI is invoked via `notebooklm tui` subcommand, registered in pyproject.toml `[project.scripts]`.
2. The TUI provides access to 11 command groups: notebook, source, artifact, chat, generate, download, label, note, collection, research, skill.
3. The layout is a three-pane static grid: Header (hard-sized), Sidebar (fixed-width), Main (flexible ratio), Footer (hard-sized). The sidebar and main are separated by a vertical divider.
4. The sidebar displays a hybrid view: a notebook list (with source counts, sortable by name and last-modified date) in the top portion, and a command tree in the bottom portion.
5. The interaction model is mouse-aware with keyboard fallback: click to select items, scroll to browse, keyboard shortcuts for power users.
6. Chat opens as a dedicated fullscreen view toggled by a key (e.g. `c`). Messages scroll in the main area, with an input bar at the bottom. Press Escape to return to the previous view.
7. Long-running operations (generate, download) run in a background thread. A spinner and progress bar display in the footer. The main pane remains interactive during background work.
8. On launch, the TUI shows the notebook list as the initial view, sorted by name (sortable by name and last mod date).
9. The theme uses a dark warm palette derived from the b08x.github.io dark mode: background #211C17, surface #2A241D, foreground #ECE3D2, accent terracotta #C97A5E, secondary dusty-blue #84A4C0, success olive #97AC78, warning burnt-orange #DB8A5C, danger brick-red #D2715F, muted #968A78.
10. The TUI uses Rich `Live` with `auto_refresh=False`. All layout updates are synchronous via `live.refresh()` in the main event loop, triggered after state mutations.
11. Each UI pane has a pure render function (header, sidebar, main, footer) that takes primitive state data and returns a Rich renderable. Renderers have no knowledge of the UI framework or Live wrapper.
12. A central state object holds all UI state (selected notebook, current view, chat history, background tasks). A main loop reads input, mutates state, calls renderers, and refreshes Live.
13. The notebook list supports sorting by name (alpha) and last-modified date, toggled via keyboard shortcut or click on column headers.
14. Each notebook entry in the sidebar displays a source count badge (e.g. "3 sources") derived from the notebook metadata.
