# Plan — NotebookLM TUI

## Solution Approach

Build a self-contained TUI module at `src/notebooklm/tui/` that wraps the existing `NotebookLMClient` async API into a Rich-based interactive terminal interface. The TUI reuses the library's public API directly — it does not shell out to the CLI or duplicate business logic. It also integrates the prompt compiler workflow from `examples/notebooklm-video/` and `examples/notebooklm-audio/` as a first-class view.

## File Structure

```
src/notebooklm/tui/
  __init__.py          # public entry: run_tui()
  app.py               # main loop, Live render trap, input dispatch
  layout.py            # static Layout grid definition
  state.py             # TUIState dataclass + view enums
  theme.py             # Rich Theme palette from dark tokens
  keypress.py          # input handling (blocking read, mouse events)
  compiler_bridge.py   # wraps prompt compilers for TUI access
  renderers/
    __init__.py
    header.py          # render_header(state) -> Rich renderable
    sidebar.py         # render_sidebar(state) -> Tree/Table
    main.py            # render_main(state) -> Panel/View
    footer.py          # render_footer(state) -> Status bar
    chat.py            # render_chat(state) -> fullscreen chat view
  views/
    __init__.py
    notebook_list.py   # notebook list view logic
    notebook_detail.py # single notebook info + sources
    source_list.py     # source management
    artifact_list.py   # artifact browser
    chat_view.py       # interactive chat
    generate_view.py   # generation triggers
    compiler_view.py   # prompt compiler: browse YAML, preview, execute
    command_palette.py # command tree for sidebar bottom
```

## Ordered Steps

### Step 1: Scaffold — `tui/__init__.py`, `state.py`, `theme.py`
**Files:** `src/notebooklm/tui/__init__.py`, `src/notebooklm/tui/state.py`, `src/notebooklm/tui/theme.py`

- `state.py`: Define `TUIState` dataclass with fields: `current_view`, `previous_view`, `selected_notebook`, `notebooks`, `chat_history`, `sort_key`, `sidebar_focus`, `background_task`, `error_message`, `compiler_state`. Define `View` enum: `NOTEBOOK_LIST`, `NOTEBOOK_DETAIL`, `SOURCE_LIST`, `ARTIFACT_LIST`, `CHAT`, `GENERATE`, `COMPILER`.
- `theme.py`: Create `THEME = Theme({...})` mapping dark palette hex values. Map: `background` -> `#211C17`, `surface` -> `#2A241D`, `foreground` -> `#ECE3D2`, `accent` -> `#C97A5E`, `secondary` -> `#84A4C0`, `success` -> `#97AC78`, `warning` -> `#DB8A5C`, `danger` -> `#D2715F`, `muted` -> `#968A78`. Add semantic keys: `header`, `sidebar`, `main`, `footer`, `border`, `prompt`.
- `__init__.py`: Export `run_tui()` function (stub initially).

**Verify:** `python -c "from notebooklm.tui import run_tui"` succeeds.

### Step 2: Layout Grid — `layout.py`
**Files:** `src/notebooklm/tui/layout.py`

- Define `build_layout() -> Layout` using `rich.layout.Layout`.
- Structure: `layout.split_column(Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3))`.
- `body.split_row(Layout(name="sidebar", size=35), Layout(name="main"))`.
- Header/footer use hard `size=` (never compress). Main uses `ratio=1` (flexible).
- Add `layout["sidebar"].split_column(Layout(name="notebooks", ratio=3), Layout(name="commands", ratio=1))`.

**Verify:** `python -c "from notebooklm.tui.layout import build_layout; print(build_layout())"` renders without error.

### Step 3: Pure Renderers — `renderers/`
**Files:** `src/notebooklm/tui/renderers/header.py`, `sidebar.py`, `main.py`, `footer.py`

Each renderer is a pure function: `def render_xxx(state: TUIState) -> Renderable`.

- `header.py`: `render_header()` returns a `Panel` with title "NotebookLM" + current profile + view name. Styled with `style="header"`.
- `sidebar.py`: `render_sidebar()` returns a `Table` with two sections. Top: notebook list with columns Name, Sources (badge), Modified. Bottom: command tree (nested `Tree`). Highlight selected row.
- `main.py`: `render_main()` dispatches to the active view renderer based on `state.current_view`. Returns a `Panel` wrapping the view content.
- `footer.py`: `render_footer()` returns status bar with keyboard hints + background task spinner/progress.

**Verify:** Each renderer can be called with a mock `TUIState` and returns a `Renderable`.

### Step 4: Render Trap + Main Loop — `app.py`
**Files:** `src/notebooklm/tui/app.py`

- `run_tui()` creates `Console(theme=THEME)`, builds `Layout`, creates `Live(layout, console=console, auto_refresh=False)`.
- Main loop: `while True:` -> read input (from `keypress.py`) -> mutate `state` -> call each renderer -> `layout["header"].update(...)`, `layout["sidebar"].update(...)`, `layout["main"].update(...)`, `layout["footer"].update(...)` -> `live.refresh()`.
- Input handling: delegate to `keypress.handle_key(key, state)`.
- Graceful exit on `q` or Ctrl+C.
- Async bridge: `asyncio.run()` wraps the async notebook fetching, running it in a background thread when needed.

**Verify:** `notebooklm tui` launches and renders the layout.

### Step 5: Input Handling — `keypress.py`
**Files:** `src/notebooklm/tui/keypress.py`

- `handle_key(key: str, state: TUIState) -> bool` returns `False` to quit.
- Mouse support: detect `MOUSE_DOWN` events from Rich, map click position to pane, update selection.
- Keyboard: `j`/`k` or arrows navigate, `Enter` selects, `Tab` switches sidebar focus, `c` opens chat, `p` opens compiler, `Escape` returns to previous view, `q` quits, `s` toggles sort, `r` refreshes.
- Use `sys.stdin` in cbreak mode for non-blocking read (per the reference pattern).

**Verify:** Navigation keys update `state.current_view` and selection index.

### Step 6: Notebook List View — `views/notebook_list.py`
**Files:** `src/notebooklm/tui/views/notebook_list.py`

- `load_notebooks(state)`: async call `NotebookLMClient.from_storage()` -> `client.notebooks.list()`. Store in `state.notebooks`. Handle errors by setting `state.error_message`.
- `render_notebook_list(state) -> Table`: render `state.notebooks` as a Rich `Table` with columns: Name (styled), Sources (badge count), Modified (relative time). Sort by `state.sort_key`.
- Sorting: `s` key toggles between `name` and `modified`. Column header click (mouse) also toggles.

**Verify:** Loads real notebooks from storage and displays them.

### Step 7: Chat Fullscreen View — `views/chat_view.py`, `renderers/chat.py`
**Files:** `src/notebooklm/tui/views/chat_view.py`, `src/notebooklm/tui/renderers/chat.py`

- `render_chat(state) -> Group`: messages as `Markdown` or `Text` renders in a scrollable list, input bar at bottom.
- `send_message(state, text)`: async call `client.chat.ask(notebook_id, text)`, append Q&A to `state.chat_history`.
- Toggle with `c` key. `Escape` returns to previous view.
- Input bar: `Prompt` renderable at bottom of chat view.

**Verify:** Chat loads, sends a message, displays response.

### Step 8: Prompt Compiler View — `views/compiler_view.py`, `compiler_bridge.py`
**Files:** `src/notebooklm/tui/views/compiler_view.py`, `src/notebooklm/tui/compiler_bridge.py`

- `compiler_bridge.py`: Wraps the existing compiler modules. Functions:
  - `list_project_configs(prompts_root) -> list[Path]`: scan `docs/prompts/` and `examples/*/projects/` for YAML configs.
  - `compile_video_project(project_file) -> CompiledPrompt`: calls `examples/notebooklm-video/compiler/prompt.compile_from_yaml()`.
  - `compile_audio_project(project_file) -> str`: calls `examples/notebooklm-audio/compiler/prompt.compile_from_yaml()`.
  - Add `src/` to `sys.path` temporarily to import the example compilers (they use relative imports).
- `compiler_view.py`: Three sub-views:
  1. **Project Browser**: list available YAML configs (video + audio), grouped by type. Select with Enter.
  2. **Preview**: show compiled prompt output (style prompt + instructions for video, full script for audio). Syntax-highlighted.
  3. **Execute**: bind to a notebook (from sidebar selection or explicit ID), trigger generation via `client.artifacts.generate_video()` or `generate_audio()`.
- Toggle with `p` key. Sub-views navigated with `Tab`/`Shift+Tab`.

**Verify:** Browse configs, preview a compiled prompt, see output.

### Step 9: Background Tasks — `app.py` (extend)
**Files:** `src/notebooklm/tui/app.py` (modify)

- `state.background_task` holds a `concurrent.futures.Future` + metadata (operation name, progress).
- Long ops (generate, download, compile+execute) submit to `ThreadPoolExecutor`, store future in state.
- Footer renderer polls future status, shows spinner (`Spinner`) while running, shows result/error when done.
- Main loop remains responsive during background work.

**Verify:** Trigger a generate, see spinner in footer, continue navigating while it runs.

### Step 10: Command Registration — `pyproject.toml`
**Files:** `pyproject.toml` (modify), `src/notebooklm/cli/__init__.py` (modify)

- Add `tui` command to the existing Click group: `@cli_group.command() def tui(): from notebooklm.tui import run_tui; run_tui()`.
- No new entry point needed — `notebooklm tui` Just Works.

**Verify:** `notebooklm tui` appears in `notebooklm --help` and launches.

### Step 11: Tests
**Files:** `tests/unit/tui/`

- `test_state.py`: test `TUIState` initialization, view transitions, sort toggling.
- `test_theme.py`: test theme has all required keys, hex values are valid.
- `test_layout.py`: test layout structure has expected named panes.
- `test_renderers.py`: test each renderer returns a `Renderable` given valid state.
- `test_keypress.py`: test key handling mutates state correctly.
- `test_compiler_bridge.py`: test compiler bridge lists configs and compiles without errors.

**Verify:** `pytest tests/unit/tui/` passes.

## Verification Commands

```bash
# After each step:
uv run python -c "from notebooklm.tui import run_tui"

# After step 10:
uv run notebooklm --help  # should show 'tui' command
uv run notebooklm tui      # should launch TUI

# After step 11:
uv run pytest tests/unit/tui/ -v
uv run ruff check src/notebooklm/tui/
uv run ruff format --check src/notebooklm/tui/
uv run mypy src/notebooklm/tui/
```

## Risks / Open Questions

1. **Async in sync loop**: The main loop is synchronous (blocking keypress read), but `NotebookLMClient` is async. Use `asyncio.run()` for initial load, then `concurrent.futures.ThreadPoolExecutor` for background async calls. This avoids needing a full asyncio event loop integration.

2. **Mouse support on all terminals**: Rich mouse mode requires terminal support. Fall back gracefully if mouse events aren't available (check `console.is_terminal` and `console.options.max_height`).

3. **Linux-only scope**: `sys.stdin` cbreak mode via `tty.setcbreak` works on Linux. No Windows portability needed.

4. **Notebook source counts**: `Notebook` objects may not include source counts directly — may need a second API call (`client.sources.list(nb_id)`) per notebook. Consider lazy-loading or caching.

5. **Compiler imports (v1 bridge, v2 overhaul)**: For v1, `compiler_bridge.py` adds `examples/notebooklm-video` and `examples/notebooklm-audio` to `sys.path` to import the compiler modules. This is fragile. Leave room to copy the compiler logic into `src/notebooklm/tui/compilers/` as a proper module in the next iteration.

6. **Artifact download formatting**: Downloaded artifacts (MP4, MP3, PDF) need proper file handling — correct extensions, mime types, and directory creation. The download view should validate the output path and show a clear success/error state.

7. **Chat history persistence**: Currently in-memory only. Could persist to a temp file, but not in scope for v1.
