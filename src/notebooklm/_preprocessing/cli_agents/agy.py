"""Antigravity CLI: ``agy -p PROMPT --output-format json [--json-schema S]``.

Envelope: one object ``{"status": "SUCCESS", "response": str, ...}``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .adapter import AgentCommandError, AgentParseError, CLIAgentAdapter, load_envelope


class AgyAdapter(CLIAgentAdapter):
    name = "agy"
    binary = "agy"
    supports_schema = True

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

    def extract_text(self, stdout: str) -> str:
        envelope = load_envelope(self.name, stdout)
        if not isinstance(envelope, dict):
            raise AgentParseError(self.name, "output envelope is not an object")
        status = str(envelope.get("status", "SUCCESS")).upper()
        if status != "SUCCESS":
            reason = envelope.get("error") or envelope.get("response") or status
            raise AgentCommandError(self.name, f"reported status {status}: {reason}")
        response = envelope.get("response")
        if response is None:
            raise AgentParseError(self.name, "envelope has no 'response'")
        return response if isinstance(response, str) else json.dumps(response)
