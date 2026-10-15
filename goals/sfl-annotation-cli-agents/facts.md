# Facts: SFL Annotations with LLM CLI Coding Agents

- An abstract CLIAgentAdapter interface defines the contract for spawning CLI agent processes, passing structured prompts, enforcing timeouts, and parsing JSON output.
- ClaudeAdapter implements headless execution via `claude -p` with JSON output formatting and schema enforcement.
- AgyAdapter implements headless execution via `agy -p` with JSON output formatting and schema enforcement.
- VibeAdapter implements headless execution via `vibe -p` with JSON output formatting.
- OpenCodeAdapter implements headless execution via `opencode run` with JSON format output.
- An adapter registry resolves adapters by name (`claude`, `agy`, `vibe`, `opencode`) and checks whether the respective CLI binary is present in PATH.
- AgentSFLEngine implements the SFL engine protocol with a hybrid pipeline: deterministic spaCy pass-1 (ideational) followed by CLI agent pass-2 (interpersonal: mood, modality, tenor).
- AgentSFLEngine supports parent-chunk batching, bundling all clauses of a parent chunk into a single CLI prompt expecting an array of structured SFL annotations.
- AgentSFLEngine supports per-clause fallback when batch processing fails or when per-clause mode is configured.
- A robust JSON extraction and repair parser extracts valid JSON payloads from CLI agent stdout, stripping markdown code fences and conversational framing.
- When a CLI agent execution fails (missing binary, timeout, or non-zero exit code), AgentSFLEngine gracefully falls back to the default DSPy engine if fallback is enabled.
- The SFL engine backend is configurable via environment variable NOTEBOOKLM_SFL_BACKEND and configuration settings.
- `notebooklm._app.sfl_tagging.default_engine` instantiates AgentSFLEngine when an agent backend is configured, enabling TUI and Web Corpus Explorer jobs to use the agent transparently.
- A CLI command `notebooklm corpus tag-sfl` allows triggering SFL tagging across a notebook or document scope with `--agent` flag selection.
- Doctor diagnostics report the availability, version, and status of supported CLI coding agents (`vibe`, `agy`, `claude`, `opencode`).
- Unit and integration tests verify CLI invocation arguments, batching, error recovery, JSON repair, and database persistence with mocked CLI processes without requiring live external agent execution.
