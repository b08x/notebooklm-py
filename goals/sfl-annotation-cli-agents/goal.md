# SFL Annotations with LLM CLI Coding Agents

## Goal

Add support for using external LLM CLI coding agents (`vibe`, `agy`, `claude`, `opencode`) to perform Systemic Functional Linguistics (SFL) annotations across the pipeline. This introduces a unified agent adapter layer, a hybrid SFL analysis engine combining deterministic spaCy pass-1 with agent-driven interpersonal pass-2, parent-chunk batching with DSPy fallback, and CLI/doctor integrations.

## Shared Understanding

The specific requirements and verifiable facts defining this work are tracked in [facts.md](facts.md).

## Execution Plan

The step-by-step implementation plan—covering the CLI agent adapters, JSON repair parser, `AgentSFLEngine` with parent-chunk batching, `_app/sfl_tagging.py` integration, `notebooklm corpus tag-sfl` command, doctor diagnostics, and test suites—is tracked in [plan.md](plan.md).

## Done Condition

This goal is considered complete when:
1. `CLIAgentAdapter` implementations for `claude`, `agy`, `vibe`, and `opencode` are implemented and tested with mock subprocess runners.
2. `AgentSFLEngine` successfully executes hybrid SFL tagging (spaCy pass-1 ideational analysis + CLI agent pass-2 interpersonal analysis) with parent-chunk batching and automatic fallback to DSPy on failure.
3. `sfl_tagging.default_engine` supports resolving the agent backend via `NOTEBOOKLM_SFL_BACKEND`, allowing TUI and Web Corpus Explorer jobs to use configured agents transparently.
4. `notebooklm corpus tag-sfl` triggers SFL tagging across scopes with `--agent` selection, and `notebooklm doctor` reports CLI agent availability.
5. All new unit and integration tests pass, and repository checks (`ruff check .`, `ruff format --check .`, `mypy src/notebooklm`, and `pytest tests/_guardrails/`) succeed cleanly.
