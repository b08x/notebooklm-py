# Facts — TUI Notebook Sorting & Navigation Enhancement

1. The TUI supports cycling between three sorting modes: Alphabetical (A-Z title), Recent Activity (last viewed / modified timestamp), and Recent Artifacts (notebooks with newest artifacts/audio first).
2. Pressing 's' in the TUI cycles through the active sort modes sequentially, updating the sidebar header indicator (e.g. `[Sort: Activity]`, `[Sort: Artifacts]`, `[Sort: Name]`).
3. Sidebar notebook rows display compact icon badges (e.g. 🎙️ for Audio Overview, 📄 for Notes/Reports, ⚡ for recent generation within 24h) reflecting artifact presence.
4. The Notebook Info / Details panel displays a rich artifact breakdown showing counts, types, recent generation relative timestamps (e.g. 'Audio · 2h ago'), and status.
5. Notebook domain/agent prefix tags (e.g. `[CLAUDE]`, `[GEMINI]`) are parsed and rendered as distinct styled chips, with hybrid section grouping in the sidebar list.
6. Pressing '/' activates an interactive live filter bar in the sidebar that filters notebook titles and tags in real time, with Escape canceling/clearing the filter.
7. The TUI provides filter toggles to restrict the displayed notebook list by artifact presence (e.g. 'has audio overview') and source count (e.g. exclude 0-source empty notebooks).
8. Discovered artifact metadata (counts, types, latest timestamps) is persisted across sessions in local cache (`~/.notebooklm/tui_cache.json` / SQLite) so sort and badge states survive restarts.
9. Artifact metadata is cached locally and loaded on-demand when a notebook is inspected in Notebook Details (or refreshed via 'r'), avoiding unsolicited background network polling that exhausts user API rate limits during list navigation.
10. The `notebooklm list` CLI command adds `--sort` options (`name`, `modified`/`recent`, `artifacts`) to maintain parity with TUI sorting capabilities.
11. The sidebar and detail panels maintain clean visual hierarchy, optical badge alignment, distinct structural borders, and instant feedback without screen redraw flicker or lag.
