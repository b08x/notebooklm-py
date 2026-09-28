# Plan — TUI Notebook Sorting & Navigation Enhancement

## Solution Approach

Scale the NotebookLM TUI and CLI to support smooth navigation of hundreds of notebooks across multiple domains. To eliminate the cognitive fatigue of scanning dense catalogs, we integrate principles from `/better-colors` and `/better-typography` to build a calm, high-contrast, scannable visual hierarchy. We implement multi-attribute sorting (Alphabetical, Recent Activity, Recent Artifacts, Creation Date), real-time search filtering (`/`), filter toggles (audio presence, non-empty sources), persistent caching of artifact metadata (`~/.notebooklm/tui_cache.json`), and disciplined visual styling (role-based domain chips, tabular counts, compact artifact badges `🎙️`/`📄`/`⚡`, and rich artifact breakdown in the Notebook Info panel). CLI parity is maintained by adding `--sort` to `notebooklm list`.

## Cognitive Load Reduction: Colors & Typography System (/better-colors, /better-typography)

### 1. Semantic Color Roles (`better-colors`)
- **One color, one meaning**: Avoid rainbow noise by assigning each color an unambiguous role across the interface:
  - `terracotta` (`#C97A5E` / `bold_accent`): Reserved strictly for active selection and focus (`▶` active notebook cursor and highlight). Static labels never borrow the accent color.
  - `cyan`: Reserved strictly for Gemini agent/domain chips (`[GEMINI]`).
  - `magenta`: Reserved strictly for Claude agent/domain chips (`[CLAUDE]`).
  - `yellow` / `amber`: Reserved for Engineering/Data chips (`[SFL]`, `[ENG]`) and the recent generation indicator (`⚡`).
  - `green` / `olive`: Reserved for Development/Testing chips (`[TEST]`, `[DEV]`) and verified states.
  - `dusty-blue` (`#84A4C0`): Reserved for audio indicators (`🎙️`) and audio duration badges.
  - `muted` (`#968A78`): Secondary metadata, unselected item text, and hotkey hints.
- **Single active highlight per view**: When scanning hundreds of rows, only the active item receives a highlighted background. All peer rows stay neutral to prevent visual competition and eye fatigue.
- **Contrast & Surfaces**: All text meets WCAG AA (>4.5:1) contrast against terminal dark surfaces (`#211C17` / `#2A241D`).

### 2. Typographic Rhythm & Scannability (`better-typography`)
- **Strict Visual Hierarchy**:
  - Header: Bold category title with muted mode descriptor: `📚 Notebooks (Recent Artifacts) [🔍 'query']`.
  - Item Row: Optical alignment of `[Prefix] [Domain Chip] [Title] [Tabular Count] [Badges]`.
  - Level descent in Notebook Info: Bold Title -> Muted Subtitle -> Two-column structured metadata table with clean key-value alignment.
- **Tabular Numbers**: Format source counts with tabular numbers (e.g. `( 2)` vs `(14)`) so numbers align vertically without visual jitter during scrolling.
- **Disciplined Truncation**: Cap notebook title length with a single unicode ellipsis (`…`) rather than three periods, preventing line wrapping in the fixed 35-column sidebar.
- **Smart Punctuation & Optical Spacing**: Use clean middle dots (` · `) between metadata attributes and standard relative time expressions (`2m ago`, `3h ago`, `Yesterday`, `Sep 15`).

## File Structure & Systems Involved

```
src/notebooklm/
  cli/
    notebook_cmd.py             # CLI `notebooklm list --sort` parity
  tui/
    app.py                      # Main loop, cache bootstrap, background trickle sync
    cache.py                    # File-locked JSON cache for summaries & artifact stats
    keypress.py                 # Keybindings: 's' cycle sort, '/' search, 'o' audio, 'z' non-empty
    renderers/
      sidebar.py                # Domain chips, artifact badges, sort/filter header, tree layout
      main.py                   # Notebook Info panel: rich artifact breakdown & relative timestamps
    state.py                    # TUIState: sort keys, search buffer, filter flags, sort/filter logic
    views/
      notebook_detail.py        # Stats and artifact fetching + caching
tests/unit/
  cli/
    test_list_sorting.py        # Unit tests for CLI `--sort` options
  tui/
    test_cache.py               # Cache concurrency and serialization tests
    test_keypress_navigation.py # Keypress tests for sort cycling, search, filters
    test_sidebar_navigation.py  # Renderer tests for chips, badges, headers
    test_main_notebook_info.py  # Renderer tests for rich artifact info panel
```

## Ordered Steps

### Step 1: Persistent Cache & TUI State Architecture
**Files:** [`src/notebooklm/tui/cache.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/cache.py), [`src/notebooklm/tui/state.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/state.py), [`src/notebooklm/tui/app.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/app.py)
**Addresses Facts:** Fact 1, Fact 8, Fact 9

- `cache.py`: Provide `TUICache` storing notebook summaries and structured artifact statistics (`total_artifacts`, `has_audio`, `has_notes`, `recent_generated_at`, `artifact_types`) in `~/.notebooklm/tui_cache.json` under file lock.
- `state.py`: Add `sort_key` supporting `"name"`, `"modified"`, `"recent-artifacts"`, and `"created"`. Add `searching: bool`, `search_query: str`, `filter_has_audio: bool`, and `filter_min_sources: bool`. Implement `cycle_sort()` and `get_filtered_and_sorted_notebooks()` incorporating cached artifact metadata.
- `app.py`: Initialize and preload `TUICache` into `state.notebook_summaries` and `state.notebook_stats` on launch, and persist on shutdown.
- **Verification:** `uv run pytest tests/unit/tui/test_cache.py`

### Step 2: Interactive Keybindings — Sort Cycling, Live Search & Filters
**Files:** [`src/notebooklm/tui/keypress.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/keypress.py), [`src/notebooklm/tui/state.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/state.py)
**Addresses Facts:** Fact 2, Fact 6, Fact 7

- In `handle_key()`:
  - `s`: Cycle active sort mode sequentially (`name` -> `modified` -> `recent-artifacts`), preserving current selection index.
  - `/`: Activate search mode when in `NOTEBOOK_LIST`, allowing typing to dynamically update `search_query` and filter the notebook list in real-time.
  - `Escape`: Clear active search query and reset filter toggles before popping view stack.
  - `o`: Toggle `filter_has_audio` to instantly show only notebooks with Audio Overviews.
  - `z`: Toggle `filter_min_sources` to exclude empty notebooks (0 sources).
  - `j`/`k`: Navigate up/down through the filtered list with proper viewport bounds clamping.
- **Verification:** `uv run pytest tests/unit/tui/test_keypress_navigation.py`

### Step 3: Sidebar Visual Hierarchy, Domain Chips & Badges (`better-colors` / `better-typography`)
**Files:** [`src/notebooklm/tui/renderers/sidebar.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/renderers/sidebar.py), [`src/notebooklm/tui/theme.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/theme.py)
**Addresses Facts:** Fact 3, Fact 5, Fact 11

- Domain Tag Parsing: Parse `[TAG]` prefixes from notebook titles and render them as color-coded chips with consistent role mapping (`[CLAUDE]` magenta, `[GEMINI]` cyan, `[SFL]` yellow).
- Compact Artifact Badges: Compute and display compact badges per notebook row:
  - `🎙️`: Has Audio Overview
  - `📄`: Has Notes or Study Guides
  - `⚡`: Generated recently (within 48 hours)
- Typographic Alignment: Format source counts with tabular alignment `( 3)` or `(12)`, and cleanly truncate long titles with unicode ellipsis `…`.
- Status Header: Display active sort mode (e.g. `(Recent Activity)`, `(Recent Artifacts)`) and active filter indicators (`🔍 'query'`, `🎙️`, `non-empty`) in the sidebar header.
- **Verification:** `uv run pytest tests/unit/tui/test_sidebar_navigation.py`

### Step 4: Rich Artifact Breakdown in Notebook Info & Details Panel
**Files:** [`src/notebooklm/tui/renderers/main.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/renderers/main.py), [`src/notebooklm/tui/views/notebook_detail.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/tui/views/notebook_detail.py)
**Addresses Facts:** Fact 4, Fact 9, Fact 11

- In `render_main` for `View.NOTEBOOK_LIST`:
  - Enhance the "Notebook Info" panel: when artifact stats are present, render a clean breakdown showing artifact count, audio overview status, and relative generation time (e.g., "Audio Overview: Ready (generated 2h ago)").
  - Format relative timestamps using clean smart punctuation (`2m ago`, `3h ago`, `Yesterday`, `Sep 15`).
- On-focus & Background Sync:
  - Cache-first strategy: `fetch_stats_if_needed(state)` and `fetch_summary_if_needed(state)` check `TUICache` first to eliminate redundant network roundtrips.
  - Rate-limit protection: To avoid draining user API rate limits, scrolling in `NOTEBOOK_LIST` remains 100% offline with zero background network requests. Unsolicited background trickle scraping is disabled; artifact metadata is persisted whenever notebooks are inspected or when explicit `[r]` (Refresh) is triggered.
- **Verification:** `uv run pytest tests/unit/tui/test_sidebar_navigation.py tests/unit/tui/test_keypress_navigation.py`

### Step 5: CLI Parity — `notebooklm list --sort`
**Files:** [`src/notebooklm/cli/notebook_cmd.py`](file:///home/b08x/WorkspaceV3/notebooklm-py/src/notebooklm/cli/notebook_cmd.py)
**Addresses Facts:** Fact 10

- Add `--sort [name|modified|created|artifacts]` to `notebooklm list`.
- Reuse `TUICache.get_all_artifact_stats()` for `--sort artifacts` so CLI users benefit from TUI-discovered generation timestamps.
- Ensure output formatting (both rich table and `--json`) preserves the sorted order.
- **Verification:** `uv run pytest tests/unit/cli/test_list_sorting.py`

### Step 6: Full Test Suite, Linting & Visual Validation
**Files:** All modified files across TUI and CLI
**Addresses Facts:** All facts (Facts 1-11)

- Run complete test suite covering CLI sorting and TUI navigation:
  `uv run pytest tests/unit/tui tests/unit/cli/test_list_sorting.py`
- Verify linting and formatting standards:
  `uv run ruff check src/notebooklm/tui src/notebooklm/cli/notebook_cmd.py`
  `uv run ruff format --check src/notebooklm/tui src/notebooklm/cli/notebook_cmd.py`

## Risks and Mitigations

- **API Rate Limits:** Fetching artifacts across hundreds of notebooks via the Google API could trigger rate-limiting errors.
  *Mitigation:* Use the persistent `TUICache`, fetch immediately only on focus/selection, and throttle any background trickle sync with `state.consume_token()`.
- **Terminal Width & Row Overflow:** Adding chips and badges to sidebar rows could cause wrapping on narrow terminals.
  *Mitigation:* Truncate title strings with an ellipsis (`…`) so the row fits comfortably within the 35-column sidebar width while keeping badges aligned.
- **Visual Clutter & Cognitive Overload:** Badges, chips, and counts together could overwhelm the user.
  *Mitigation:* Adhere strictly to the `/better-colors` "one color, one meaning" rule and `/better-typography` tabular alignment so that unselected rows remain calm, with color reserved for functional discrimination.
