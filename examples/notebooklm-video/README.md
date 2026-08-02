# NotebookLM Modular Video Orchestration & Prompt Compiler

This reference architecture demonstrates how to treat `notebooklm-py` strictly as an execution and network transport layer while cleanly decoupling prompt engineering, visual styles, domain concepts, and narrative tones into reusable, declarative layers.

## Architecture & Python 2025 Principles

Adhering to modern Python design patterns, this orchestration layer enforce a strict boundary between computation and I/O:

1. **Synchronous Prompt Compiler (`compiler/`)**: CPU-bound, zero-network processing. Loads modular YAML packs, performs automatic semantic style inference, validates structures using **Pydantic v2**, and compiles expressive prompt strings via **Jinja2**.
2. **Asynchronous Execution Runner (`runner.py`)**: I/O-bound pipeline utilizing `notebooklm-py`'s async `NotebookLMClient` to initialize notebooks, upload document sources, initiate remote Studio rendering, poll completion status, and download final `.mp4` video artifacts.

```
                  Project Config (.yaml)
                           │
      ┌────────────────────┼────────────────────┐
      ▼                    ▼                    ▼
Style Pack (YAML)    Domain Pack (YAML)   Voice Pack (YAML)
      │                    │                    │
      └────────────────────┼────────────────────┘
                           │ (Sync Pydantic/Jinja2 Compilation)
                           ▼
                  CompiledPrompt
                           │ (Async Transport)
                           ▼
                 NotebookLMClient (RPC)
                           │
                 NotebookLM Video Overview (.mp4)
```

## Prompt Library Locations

By default, the compiler reads from the modular prompt pack repository located at [`../../docs/prompts/video/`](file:///home/b08x/WorkspaceV3/notebooklm-py/docs/prompts/video):
- **Styles**: `styles/` (`watercolor-atlas.yaml`, `pixel-simulation.yaml`, `research-notebook.yaml`, `illustrated-town.yaml`, `metro-map.yaml`, `strategy-game.yaml`, `laboratory-notebook.yaml`)
- **Domains**: `domains/` (`software-architecture.yaml`, `nutrition.yaml`, `radiology.yaml`, `history.yaml`, `machine-learning.yaml`)
- **Voices**: `voices/` (`documentary.yaml`, `technical-explainer.yaml`, `socratic.yaml`)

You can override this location by setting the `NOTEBOOKLM_PROMPT_LIBRARY` environment variable.

## Quickstart & Usage

### 1. Preview Compilation (Dry-Run / Zero Network Calls)
Test prompt assembly, inspect visual grammar transformations, and verify semantic grammar selection without hitting NotebookLM servers or requiring credentials:

```bash
# Preview default project (ai-agents.yaml)
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-video/runner.py

# Preview automatic semantic grammar inference project
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-video/runner.py examples/notebooklm-video/projects/auto-inferred-ml.yaml
```

### 2. Live Execution & Video Generation
When authenticated with NotebookLM (`notebooklm login` or valid context in `~/.notebooklm`), attach the `--execute` flag to run the async transport and download the resulting video overview:

```bash
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-video/runner.py examples/notebooklm-video/projects/radiology.yaml --execute --out radiology_overview.mp4
```

## Automatic Semantic Grammar Selection

If a project sets `style: auto-infer` (see `projects/auto-inferred-ml.yaml`), the prompt compiler evaluates domain affinity tables and performs keyword extraction over document titles, domain tags, and readable local text files to automatically recommend and apply the most cohesive visual style pack (e.g., matching machine learning topics to the `laboratory-notebook` style).
