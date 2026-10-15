"""OpenCode: ``opencode run --format json [-m MODEL] -- PROMPT``.

Envelope: newline-delimited JSON events. The answer is the concatenation of
``{"type": "text", "part": {"text": ...}}`` events; an ``{"type": "error"}``
event marks a failed run. OpenCode has no schema flag.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .adapter import AgentCommandError, AgentParseError, CLIAgentAdapter


class OpenCodeAdapter(CLIAgentAdapter):
    name = "opencode"
    binary = "opencode"

    def build_argv(
        self, executable: str, prompt: str, schema: Mapping[str, Any] | None
    ) -> list[str]:
        argv = [executable, "run", "--format", "json"]
        if self.model:
            argv += ["-m", self.model]
        if self.agent:
            argv += ["--agent", self.agent]
        if self.workdir:
            # opencode resolves project agents from <dir>/.opencode/agents.
            argv += ["--dir", self.workdir]
        return argv + list(self.extra_args) + ["--", prompt]

    def extract_text(self, stdout: str) -> str:
        texts: list[str] = []
        events = 0
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            events += 1
            if event.get("type") == "error":
                error = event.get("error") or event.get("part") or "unknown error"
                raise AgentCommandError(self.name, f"reported error: {error}")
            part = event.get("part")
            if event.get("type") == "text" and isinstance(part, dict):
                texts.append(str(part.get("text", "")))
        if not events:
            raise AgentParseError(self.name, "no JSON events in output")
        text = "".join(texts)
        if not text.strip():
            raise AgentParseError(self.name, "no text events in output")
        return text
