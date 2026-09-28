# Goal — TUI Notebook Sorting & Navigation Enhancement

## Articulated Goal

Enhance the NotebookLM TUI and CLI to seamlessly discover and navigate hundreds of notebooks across multiple domains. Deliver multi-attribute sorting (Alphabetical, Recent Activity, Recent Artifacts, Creation Date), real-time search filtering (`/`), filter toggles (audio presence, non-empty sources), persistent caching of artifact metadata, and a calm, low-cognitive-load visual hierarchy using principles from `/better-colors` and `/better-typography`.

## Reference

- **Facts:** [`goals/tui-notebook-navigation/facts.md`](facts.md) — 11 accepted facts covering sorting modes, keybindings, artifact badges, domain chips, live search, metadata caching, background sync, CLI parity, and visual hierarchy.
- **Plan:** [`goals/tui-notebook-navigation/plan.md`](plan.md) — 6-step implementation plan with file structure, ordered steps, verification commands, and risk notes.

## Done Condition

- `s` cycles through Alphabetical, Recent Activity, and Recent Artifacts sorting modes in the TUI, with sidebar header reflecting the active mode.
- `/` triggers real-time interactive search filtering of notebook titles and domain tags, and `Escape` clears active filters.
- `o` and `z` toggle audio overview presence and non-empty source filters.
- Notebook domain/agent tags (`[CLAUDE]`, `[GEMINI]`, etc.) render as cleanly styled, role-assigned chips.
- Compact artifact badges (`🎙️`, `📄`, `⚡`) display in the sidebar rows with tabular number alignment, and the Notebook Info panel displays rich artifact breakdown and relative timestamps.
- Discovered artifact metadata persists across sessions in `~/.notebooklm/tui_cache.json`.
- `notebooklm list --sort` supports `name`, `modified`, `created`, and `artifacts`.
- All unit and integration tests pass, with clean ruff linting.
