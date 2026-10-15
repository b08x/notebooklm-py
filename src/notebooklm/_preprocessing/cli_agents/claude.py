"""Claude Code: ``claude -p PROMPT --output-format json [--json-schema S]``.

Envelope: one object ``{"type": "result", "is_error": bool, "result": str,
"structured_output": ...}``. ``structured_output`` is present only when
``--json-schema`` was passed and validated.

Billing: an inherited ``ANTHROPIC_API_KEY`` / ``ANTHROPIC_AUTH_TOKEN`` takes
precedence over the claude.ai subscription login (``claude auth status`` then
reports ``authMethod: api_key``), so every annotation would be billed per token.
Both are removed from the child environment unless
``NOTEBOOKLM_CLAUDE_USE_API_KEY=1``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from typing import Any

from .adapter import AgentCommandError, AgentParseError, CLIAgentAdapter, load_envelope

USE_API_KEY_ENV = "NOTEBOOKLM_CLAUDE_USE_API_KEY"
API_KEY_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


class ClaudeAdapter(CLIAgentAdapter):
    name = "claude"
    binary = "claude"
    supports_schema = True

    def stripped_env_vars(self) -> tuple[str, ...]:
        """Drop API-key auth so the CLI uses the subscription login."""
        opt_in = os.environ.get(USE_API_KEY_ENV, "").strip().lower()
        return () if opt_in in ("1", "true", "yes", "on") else API_KEY_VARS

    def build_argv(
        self, executable: str, prompt: str, schema: Mapping[str, Any] | None
    ) -> list[str]:
        argv = [executable, "-p", prompt, "--output-format", "json"]
        if schema is not None:
            argv += ["--json-schema", json.dumps(schema)]
        if self.model:
            argv += ["--model", self.model]
        if self.agent:
            argv += ["--agent", self.agent]
        return argv + list(self.extra_args)

    def _envelope(self, stdout: str) -> dict[str, Any]:
        envelope = load_envelope(self.name, stdout)
        if isinstance(envelope, list):
            # stream-json style: the final ``result`` event carries the answer.
            results = [e for e in envelope if isinstance(e, dict) and e.get("type") == "result"]
            envelope = results[-1] if results else None
        if not isinstance(envelope, dict):
            raise AgentParseError(self.name, "output envelope is not an object")
        if envelope.get("is_error") or envelope.get("subtype", "success") != "success":
            reason = envelope.get("result") or envelope.get("subtype") or "unknown error"
            raise AgentCommandError(self.name, f"reported error: {reason}")
        return envelope

    def structured_payload(self, stdout: str) -> Any | None:
        return self._envelope(stdout).get("structured_output")

    def extract_text(self, stdout: str) -> str:
        result = self._envelope(stdout).get("result")
        return result if isinstance(result, str) else json.dumps(result)
