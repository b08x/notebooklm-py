"""Mistral Vibe: ``vibe -p PROMPT --output json``.

Envelope: a JSON array of session entries. The answer is the text content of
the last ``{"type": "message", "role": "assistant"}`` entry. Vibe has no
schema flag, so the schema is enforced by the prompt and the repair parser.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .adapter import AgentParseError, CLIAgentAdapter, load_envelope


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type", "text") == "text"
        )
    return ""


class VibeAdapter(CLIAgentAdapter):
    name = "vibe"
    binary = "vibe"

    def build_argv(
        self, executable: str, prompt: str, schema: Mapping[str, Any] | None
    ) -> list[str]:
        # Vibe has no model flag; ``model`` is ignored. ``--agent`` selects a
        # profile from ~/.vibe/agents/NAME.toml.
        argv = [executable, "-p", prompt, "--output", "json"]
        if self.agent:
            argv += ["--agent", self.agent]
        if self.workdir:
            argv += ["--workdir", self.workdir]
        return argv + list(self.extra_args)

    def extract_text(self, stdout: str) -> str:
        envelope = load_envelope(self.name, stdout)
        entries = envelope if isinstance(envelope, list) else [envelope]
        for entry in reversed(entries):
            if (
                isinstance(entry, dict)
                and entry.get("role") == "assistant"
                and entry.get("type", "message") == "message"
            ):
                text = _content_text(entry.get("content"))
                if text.strip():
                    return text
        raise AgentParseError(self.name, "no assistant message in output")
