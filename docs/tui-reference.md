# TUI Reference

**Status:** Active
**Last Updated:** 2026-09-17

Command reference for the interactive Terminal User Interface (`notebooklm tui`). The TUI is a single-key, non-blocking keyboard interface (`src/notebooklm/tui/`) built on `rich.Live`; it does not accept line-edited shell commands — every action below is a single keystroke, except where a view puts you into a text-input mode.

> This document is generated from `src/notebooklm/tui/keypress.py`'s actual dispatch logic, not from the in-app footer hint bar, which is currently stale (it omits several bindings documented here — see [Known gaps](#known-gaps)).

## Launching

```bash
notebooklm tui
```

Loads the notebook list, then enters the interactive loop. `Ctrl+C` exits at any time.

> **Not this:** the separate `notebooklm-tui` console script (`notebooklm.tui.__main__`) is a different, mostly-stub Click group — its `start` subcommand only prints "Starting TUI..." and does not launch the interactive loop above; its `ingest <notebook_id> <source_id>` subcommand is a one-shot CLI wrapper around the same ingestion pipeline the TUI's own "Ingest Sources" action uses. Use `notebooklm tui` for the interactive interface.

## Views

| View | Enter with | Leave with |
|---|---|---|
| Notebook List | (default on launch), or `n` from anywhere with no notebook selected | `Enter` on a notebook → Notebook Detail |
| Notebook Detail | `Enter` from Notebook List, or `n` from anywhere once a notebook is selected | `Esc` → previous view; menu actions also return here |
| Chat | `c` or `Tab` (from anywhere) | `Esc` or `Tab` |
| Compiler | `p` (from anywhere) | `Esc` |
| Assessment | `A` (from anywhere) | `Esc` |
| Logs | `L` (from anywhere) | `Esc` |
| Context edit (overlay) | `e` (from Notebook Detail, with a notebook selected) | `Enter` (save) or `Esc` (cancel) |
| Source-selection picker (overlay) | `Enter` on Notebook Detail's "Ingest Sources" menu item, once sources finish loading | `Enter` (confirm, starts ingestion) or `Esc` (cancel) |

## Global commands

Available from any view (checked after view-specific handling, so a view's own bindings for the same key — e.g. `j`/`k` for scrolling — take precedence where both are defined):

| Key | Action |
|---|---|
| `q` | Quit the TUI |
| `n` | Jump to the selected notebook's Notebook Detail (or Notebook List, if none is selected) from anywhere |
| `c` or `Tab` | Switch to Chat view |
| `p` | Switch to Compiler view |
| `A` | Switch to Assessment view |
| `L` | Switch to [Logs view](#logs) |
| `Esc` | Return to the previous view (or clear active search/filters in Notebook List) |
| `s` | Cycle Notebook List sort mode (Alphabetical → Recent Activity → Recent Artifacts) |
| `↑` / `↓` | Aliased to `k` / `j` respectively, everywhere |

> `Esc` only holds a single-slot "previous view," which gets overwritten by the next `c`/`p`/`A`/`L`/`n` jump and is cleared after one use — it does not chain back through multiple hops. Use `n` to jump straight back to your notebook rather than stacking `Esc` presses.

## Notebook List

| Key | Action |
|---|---|
| `j` / `k` | Move selection down/up (auto-scrolls once the selection passes the last visible row; the row count follows terminal height) |
| `Enter` | Open the selected notebook in Notebook Detail |
| `s` | Cycle sort mode: Alphabetical (A-Z) → Recent Activity → Recent Artifacts |
| `/` | Activate live search mode (filters titles and domain tags in real time) |
| `Esc` | Clear active search query and reset filter toggles |
| `o` | Toggle filter to show only notebooks with an Audio Overview |
| `z` | Toggle filter to show only non-empty notebooks (minimum 1 source) |
| `r` | Refresh notebook list from server |

### Visual Hierarchy & Badges

- **Domain Tags**: Notebook titles with `[TAG]` prefixes render the tag as a lowercase colored word before the title (`gemini` blue, `claude` pink, `sfl`/`eng` amber, `test`/`dev` green, others gray).
- **Compact Artifact Badges**: Single-cell glyphs show asset availability (emoji are avoided because terminals draw them two cells wide, which misaligns rows):
  - `♪` Audio Overview generated
  - `≡` Notes, reports, or documents present
  - `✦` Recent generation activity (within the last 48 hours)
- **Right-Aligned Counts**: Source counts sit in a right-aligned column; long titles are truncated with `…` to the sidebar's width instead of wrapping.

### Notebook Info & Metadata Caching

- **Notebook Info Panel**: Displays notebook title, source count, and a two-column breakdown of artifact statistics: total artifact count, artifact types, audio overview status with relative time (`● Ready  2h ago`), and last generated relative timestamp.
- **Persistent Cache**: Discovered artifact metadata and summaries are persisted in `~/.notebooklm/tui_cache.json` under file lock, enabling instant offline list navigation with zero background network requests. Explicit refresh (`r` in Notebook Detail) forces a live server re-fetch.


## Notebook Detail

A numbered action menu for the selected notebook:

| Key | Action |
|---|---|
| `j` / `k` | Move menu selection down/up (clamped to the 4 items) |
| `Enter` | Run the highlighted menu action |
| `e` | Open the [context-edit overlay](#context-edit-overlay) for this notebook |

Menu items (select with `j`/`k`, run with `Enter`):

1. **Chat with Notebook** — switches to Chat view for this notebook.
2. **Download Assets (Sources, Overviews)** — downloads every source's full text (as Markdown) and the chat history to `./<Notebook Title>_assets/` in the current working directory. Runs in the background; failures per-source are swallowed silently (best-effort).
3. **Ingest Sources into Database (Pipeline)** — fetches the notebook's sources in the background, then opens the [source-selection picker](#source-selection-picker) (all sources pre-selected by default). Confirming starts ingestion: chunks, embeds (in batches — see [Logs](#logs) for per-batch progress), and persists the selected sources' full text into the local Postgres/pgvector clause store (`IngestionService.ingest_source` per source), making it searchable via `search_clauses`. Runs in the background; per-source failures are reported live (see the Notebook List detail panel and the footer while it runs) and summarized (count + first error) once all sources are attempted, without aborting the batch.
4. **Assess Audio Overview** — downloads the notebook's most recent generated audio overview, transcribes it, runs it through the NLP preprocessing pipeline (chunking, spaCy entity annotation), ingests the resulting chunks into the clause store, and switches to Assessment view to display/grade the result.

Both "Ingest Sources" and "Assess Audio Overview" use this notebook's customized embedding context if one was saved (see below), otherwise the notebook's own AI-generated summary is fetched automatically and used as context — no separate LLM call is made for this.

## Source-selection picker

Opened by confirming Notebook Detail's "Ingest Sources" menu item, after that notebook's sources finish loading in the background (the Notebook Detail view stays up with a "Loading sources..." status until then).

| Key | Action |
|---|---|
| `j` / `k` | Move the highlighted source down/up |
| `Space` | Toggle the highlighted source's selection |
| `a` | Select all sources |
| `n` | Select none |
| `Enter` | Start ingestion for the currently-selected sources |
| `Esc` | Cancel — returns to Notebook Detail, ingestion does not start |

All sources are pre-selected by default (matching the old "ingest everything" behavior) — deselect the ones you don't want before confirming.

## Context-edit overlay

Entered with `e` from Notebook Detail. Lets you override the text used as contextual-embedding prefix (prepended to each chunk before embedding, contextual-retrieval style) for this notebook's ingestion and audio-overview assessment runs.

| Key | Action |
|---|---|
| *(printable char)* | Append to the edit buffer |
| Backspace | Delete the last character |
| `Enter` | Save the buffer as this notebook's context override and close the overlay |
| `Esc` | Discard changes and close the overlay |

The buffer is seeded from this notebook's existing override if one was saved, otherwise from its cached auto-fetched summary. Saving an empty buffer disables the context prefix entirely for that notebook (equivalent to `context=""`); if no override is ever saved, ingestion/assessment fall back to auto-fetching the notebook summary each run.

## Chat

Free-text input targeting `client.chat.ask` for the current notebook — **separate from** the clause-search MCP tool (`search_clauses`), which queries this project's own local ingested-clause store instead of NotebookLM's own chat.

| Key | Action |
|---|---|
| *(printable char)* | Append to the chat input buffer |
| Backspace | Delete the last character |
| `Enter` | Send the current input as a chat message (no-op if blank/whitespace-only) |
| `Esc` or `Tab` | Return to the previous view |

## Compiler

Lists local compiler project configs (`compiler_bridge.list_project_configs`) and compiles the selected one (audio or video project) into a preview.

| Key | Action |
|---|---|
| `j` / `k` | Move config selection down/up |
| `Enter` | Compile the selected config and show its preview |
| `Esc` | Return to the previous view |

## Assessment

Displays the chunked/annotated result of an "Assess Audio Overview" run, with per-chunk entity highlighting and fact-check gutters.

| Key | Action |
|---|---|
| `j` / `k` | Scroll down/up |
| `Enter` | Trigger LLM-based assessment grading (scoring) of the current chunks |
| `f` | Run SIFT fact-checking against the current chunks |
| `y` | (During HITL prompt) Confirm as meta-dialogue/satire and skip fact-checking |
| `n` | (During HITL prompt) Reject classifier assumption and force fact-checking |
| `s` | (During HITL prompt) Toggle Auto-Skip for meta-dialogue (bypasses future prompts) |
| `Esc` | Return to the previous view |

## Logs

Live-tails application log output (the last 200 of up to 500 buffered records), color-coded by level. Logging is routed here instead of stdout/stderr specifically so it doesn't corrupt the full-screen `rich.Live` render — before this existed, every logger below `ERROR` was silently dropped, which hid the detail needed to diagnose a background failure (e.g. an Ollama embedding timeout during ingestion).

| Key | Action |
|---|---|
| `Esc` | Return to the previous view |

Captured level defaults to `INFO`; set `NOTEBOOKLM_TUI_LOG_LEVEL=DEBUG` (or another level name) before launching for more detail, e.g. full HTTP/SQL tracing.

While a background ingestion is running, this view (like the footer and the Notebook List detail panel) redraws every tick even without a keypress, so new log lines and progress appear live.

## Known gaps

- The in-app footer hint bar (`renderers/footer.py`) lists `q`, `n`, `c`, `p`, `A`, `L`, `Tab`, `j`/`k`, `Esc` — still missing `s` (sort), `e` (customize context), `f` (fact-check), and it doesn't change per-view. This document reflects the actual dispatch logic in `keypress.py`, not the footer text.
- `notebooklm-tui start` (the separate console-script entry point) does not launch the interactive loop — see the note under [Launching](#launching).
