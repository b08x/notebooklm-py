# NotebookLM Automated Audio Orchestration & Zero-Touch Slot Binding

This reference orchestration pipeline solves the problem of manually filling out prompt templates (such as `[INSERT UUID]`, `[INSERT Scope]`, or hunting down diagnostic terms in source texts). It treats `notebooklm-py` as an automated extraction and audio rendering engine while using declarative configurations and **Jinja2** to compile dialogue synthesis scripts with zero human intervention.

## Architectural Flow & Automated RAG Binding

When working with an **existing notebook**, the automated audio compiler executes a two-stage binding process:

1. **Metadata Auto-Binding (`compiler/auto_bind.py`)**: Connects to your target notebook UUID via `NotebookLMClient` to dynamically extract the exact Notebook Title and analyze all ingested source titles to build the `<SOURCE_BINDING>` Scope string automatically.
2. **Dynamic Vocabulary Harvesting (RAG Interrogation)**: When `auto_extract: true` is enabled in your YAML specification, the runner triggers a fast analytical chat query (`client.chat.ask(notebook_id, query)`) instructing NotebookLM to interrogate its own ingested document corpus and extract real source-grounded diagnostic failure modes (agreement, confusion, frustration, tangent) and structured debate topics. These are passed directly into the Jinja2 rendering template (`mr_and_mrs_language_model.j2`).

```
                    Audio Project (.yaml)
                             │
                             ▼
              AudioProjectConfig (Pydantic v2)
                             │
          [Is auto_extract: true & notebook_id set?]
                             │
                Yes ┌────────┴────────┐ No
                    ▼                 ▼
          auto_populate_from_notebook │
           (RAG vocabulary & scope    │
            extraction via SDK)       │
                    │                 │
                    ▼                 ▼
          Jinja2 Zero-Touch Script Compilation
            (All [INSERT ...] slots populated)
                             │
                             ▼
         client.artifacts.generate_audio(instructions)
                             │
             Diagnostic Dialogue Audio (.mp3)
```

## Quickstart & Usage

### 1. Dry-Run Compilation Preview (Offline / No API Calls)

Inspect how the compiler parameterizes templates and replaces manual slots using declarative defaults or YAML dictionary substitutions without connecting to Google servers:

```bash
# Preview offline telemetry customization
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-audio/runner.py examples/notebooklm-audio/projects/custom-telemetry-session.yaml

# Preview template structure targeting an existing notebook
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-audio/runner.py examples/notebooklm-audio/projects/existing-notebook-auto-rag.yaml
```

### 2. Zero-Touch Live Execution & RAG Extraction on Existing Notebooks

When authenticated (`notebooklm login`), point the runner to an existing notebook UUID with `--execute`. The pipeline will dynamically query the notebook's documents, harvest technical failure vocabulary, compile the completed instructions, and download the resulting MP3 audio session:

```bash
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-audio/runner.py \
  examples/notebooklm-audio/projects/existing-notebook-auto-rag.yaml \
  -n <YOUR_EXISTING_NOTEBOOK_UUID> \
  --execute \
  --out diagnostic_session.mp3
```

The pipeline passes the YAML's `audio_format` and `audio_length` through to `client.artifacts.generate_audio` (`"default"` means the API default; valid choices: `deep-dive`, `brief`, `critique`, `debate` and `short`, `default`, `long`).

### 3. Emit-Only Mode (pipe into `notebooklm generate audio`)

`--emit` runs the auto-bind step, then prints **only** the compiled prompt to stdout (diagnostics go to stderr), so it can be piped straight into the CLI's generate command:

```bash
uv run --with pyyaml --with pydantic --with jinja2 examples/notebooklm-audio/runner.py \
  examples/notebooklm-audio/projects/sfl-engine-pipeline-mechanics.yaml \
  -n <YOUR_EXISTING_NOTEBOOK_UUID> \
  --emit \
  | notebooklm generate audio --prompt-file - -n <YOUR_EXISTING_NOTEBOOK_UUID> --no-wait
```

`--emit` requires `-n` / `--notebook-id`.

### 4. From the TUI (compile → review → edit → generate)

`notebooklm tui` (Compiler view, `p`) drives this whole compiler interactively: select a project YAML, `Enter` compiles it against the notebook selected in the sidebar, `e` edits the prompt in `$EDITOR`, `g` + `y` generates with the YAML's format and length. Slot filling prefers the notebook's **ingested clauses** (hybrid Postgres full-text + pgvector retrieval merged by Reciprocal Rank Fusion, then one LLM call) — the chat-based `auto_bind` extraction above is the fallback when nothing is ingested. Finished MP3s land in `~/Archive/NotebookLM/audio/<project-slug>/` with a sidecar JSON recording the exact prompt sent. See the [TUI Reference](../../docs/tui-reference.md#compiler) for the keys.

## Customizing Telemetry without Editing Markdown Templates

Instead of manually editing verbose markdown templates, you can override specific parameters directly in your concise project YAML:

```yaml
title: "Production Lock Synchronizer"
source_type: "notebook"
auto_extract: false   # Disable RAG auto-extraction if providing custom dictionary below

lexical_dictionary:
  agreement: "[State 1: Quorum consensus confirmed via Raft voting]"
  confusion: "[State 2: Split-brain fencing token divergence]"
  frustration: "[State 3: Connection pool eviction & socket read timeout]"
  brainstorm: "[State 4: Unenforced optimistic concurrency fallback]"

telemetry:
  scaling_var: "network jitter packet drop ratio"
  coefficient: 1.42
```
