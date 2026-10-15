# Implementation Plan: SFL Annotations with LLM CLI Coding Agents

## Solution Approach

Extend the Systemic Functional Linguistics (SFL) annotation subsystem to support external LLM CLI coding agents (`vibe`, `agy`, `claude`, `opencode`) as pluggable backends alongside the default DSPy engine.

The solution consists of:
1. An extensible CLI agent adapter framework (`CLIAgentAdapter`) with concrete adapters for Claude Code (`claude -p`), Antigravity CLI (`agy -p`), Mistral Vibe (`vibe -p`), and OpenCode (`opencode run`), supported by a resilient JSON extraction/repair pipeline.
2. An `AgentSFLEngine` implementing a hybrid pipeline: deterministic spaCy pass-1 (ideational analysis) paired with agent-driven pass-2 (interpersonal analysis: mood, modality, tenor). To eliminate CLI process spawn overhead, `AgentSFLEngine` provides parent-chunk batching (`forward_batch`), with per-clause and DSPy fallback.
3. Pluggable configuration in `_app/sfl_tagging.py` via `NOTEBOOKLM_SFL_BACKEND`, seamlessly enabling the TUI and Web Corpus Explorer to leverage the configured agent.
4. CLI command `notebooklm corpus tag-sfl` and doctor diagnostics reporting agent availability.

---

## Ordered Steps

### Step 1: Core CLI Agent Abstraction & JSON Repair Parser
- **Systems/Files**:
  - `src/notebooklm/_preprocessing/cli_agents/__init__.py`
  - `src/notebooklm/_preprocessing/cli_agents/adapter.py`: Define `CLIAgentAdapter` Protocol, `AgentCommandError`, `AgentParseError`, and execution models.
  - `src/notebooklm/_preprocessing/cli_agents/parser.py`: Robust JSON extractor and repair function (`extract_and_repair_json`) handling markdown fences, conversational preambles, and malformed quotes.
- **Verification**:
  - Create `tests/unit/test_cli_agent_json_parser.py` testing clean JSON, fenced code blocks, conversational prefixes, nested lists/dicts, and corrupted strings.
  - Command: `uv run pytest tests/unit/test_cli_agent_json_parser.py`

### Step 2: Concrete CLI Agent Adapters & Registry
- **Systems/Files**:
  - `src/notebooklm/_preprocessing/cli_agents/claude.py`: `ClaudeAdapter` running `claude -p --output-format json` with schema validation.
  - `src/notebooklm/_preprocessing/cli_agents/agy.py`: `AgyAdapter` running `agy -p --output-format json` with schema validation.
  - `src/notebooklm/_preprocessing/cli_agents/vibe.py`: `VibeAdapter` running `vibe -p --output json`.
  - `src/notebooklm/_preprocessing/cli_agents/opencode.py`: `OpenCodeAdapter` running `opencode run --format json`.
  - `src/notebooklm/_preprocessing/cli_agents/registry.py`: Registry for lookup by agent name, PATH presence check (`shutil.which`), and adapter enumeration.
- **Verification**:
  - Create `tests/unit/test_cli_agent_adapters.py` mocking subprocess execution to verify CLI arguments, timeouts, environment passing, and stdout parsing for all 4 agents.
  - Command: `uv run pytest tests/unit/test_cli_agent_adapters.py`

### Step 3: AgentSFLEngine Implementation (Hybrid Pipeline & Batching)
- **Systems/Files**:
  - `src/notebooklm/_preprocessing/cli_agents/sfl_engine.py`: `AgentSFLEngine` implementing `forward(utterance)` and `forward_batch(clauses)`.
  - Connects deterministic spaCy pass-1 (participants, processes, circumstances) with agent pass-2 (mood, modality, tenor).
  - Handles parent-chunk batch prompts with JSON schema constraints.
  - Implements fallback to default DSPy `SFLEngine` on agent timeout or non-zero exit code.
  - Re-export `AgentSFLEngine` in `src/notebooklm/_preprocessing/sfl_engine.py`.
- **Verification**:
  - Create `tests/unit/test_agent_sfl_engine.py` testing hybrid pass execution, parent-chunk batching, per-clause fallback, and DSPy fallback.
  - Command: `uv run pytest tests/unit/test_agent_sfl_engine.py`

### Step 4: Tagging Pipeline Integration & Configuration
- **Systems/Files**:
  - `src/notebooklm/_app/sfl_tagging.py`:
    - Update `default_engine()` to inspect `NOTEBOOKLM_SFL_BACKEND` env var and settings, instantiating `AgentSFLEngine` when configured.
    - Enhance `tag_children()` to detect `forward_batch` on the engine, batching parent-chunk clauses in a single invocation while preserving monotonic `GroupProgress.child` callbacks and transaction safety.
- **Verification**:
  - Create `tests/unit/test_sfl_tagging_agent.py` testing `tag_children` with `AgentSFLEngine` and batching.
  - Regression check: `uv run pytest tests/unit/test_sfl_tagging.py`
  - Guardrail check: `uv run pytest tests/_guardrails/test_app_boundary.py`

### Step 5: CLI Command (`notebooklm corpus tag-sfl`) & Doctor Diagnostics
- **Systems/Files**:
  - `src/notebooklm/_app/doctor.py`: Add diagnostics checking installed CLI coding agents (`vibe`, `agy`, `claude`, `opencode`), version string, and path.
  - `src/notebooklm/cli/corpus_cmd.py`: Implement `notebooklm corpus tag-sfl` supporting `--agent`, `--batch/--no-batch`, scope selection, and `--json` output.
  - `src/notebooklm/cli/__init__.py` & `src/notebooklm/notebooklm_cli.py`: Register `corpus` command group.
- **Verification**:
  - Create `tests/unit/cli/test_corpus_cmd.py` and `tests/unit/app/test_doctor_agents.py`.
  - Guardrail check: `uv run pytest tests/_guardrails/test_cli_boundary.py`
  - Commands: `uv run notebooklm --help` and `uv run notebooklm doctor --json`

### Step 6: End-to-End System Verification, Formatting & Linting
- **Systems/Files**:
  - All new and modified files across `src/notebooklm/` and `tests/`.
- **Verification**:
  - Run full test suite for touched modules:
    `uv run pytest tests/unit/test_cli_agent_*.py tests/unit/test_agent_sfl_engine.py tests/unit/test_sfl_tagging*.py tests/unit/cli/test_corpus_cmd.py`
  - Formatting and typing checks:
    `uv run ruff check .`
    `uv run ruff format --check .`
    `uv run mypy src/notebooklm`
  - Guardrail compliance:
    `uv run pytest tests/_guardrails/`

---

## Risks and Mitigations

- **Process startup overhead**: Spawning CLI agent binaries per single clause would be slow for long transcripts.
  - *Mitigation*: Implemented parent-chunk batching (`forward_batch`), sending all clauses of a parent chunk in one CLI invocation.
- **Unstructured / conversational CLI outputs**: LLM CLI agents may emit formatting, conversational preamble, or ANSI escape codes.
  - *Mitigation*: Force `--output-format json` / `--json-schema` where supported, paired with `extract_and_repair_json` stripping fences and non-JSON preamble.
- **Missing CLI agent binaries or expired sessions**: Users or CI environments may not have all 4 agents installed or authenticated.
  - *Mitigation*: Adapter registry checks binary presence via `shutil.which`. If an agent is missing or fails, `AgentSFLEngine` gracefully falls back to DSPy `SFLEngine`. All test suites use mock subprocess execution.
