# Goal — NotebookLM TUI

## Articulated Goal

Build a Rich-based terminal UI for notebooklm-py that provides persistent interactive access to notebooks, sources, artifacts, chat, and the prompt compiler system — wrapped in a three-pane layout with a dark warm theme, mouse support, and background task execution.

## Reference

- **Facts:** `goals/notebooklm-tui/facts.md` — 14 accepted facts covering entry point, scope, layout, interaction model, chat, async execution, theme, and architecture.
- **Plan:** `goals/notebooklm-tui/plan.md` — 11-step implementation plan with file structure, ordered steps, verification commands, and risk notes.

## Done Condition

- `notebooklm tui` launches a functional TUI in the terminal
- Notebook list loads from real storage and displays with source counts
- Sidebar shows hybrid notebook list + command tree
- Chat view opens fullscreen, sends messages, displays responses
- Compiler view browses YAML configs, previews compiled prompts
- Background tasks show spinner/progress in footer
- Theme matches the dark warm palette from b08x.github.io
- All unit tests pass, ruff/mypy clean
