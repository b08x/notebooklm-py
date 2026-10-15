"""DSPy language model backed by an LLM CLI coding agent.

:class:`CLIAgentLM` lets every DSPy program in the repo (SFL pass 2, SIFT
fact-checks, the corpus agent, compiler generation) run on ``claude``, ``agy``,
``vibe`` or ``opencode`` instead of an HTTP provider. Each completion is one
headless agent invocation: the chat messages are flattened into a single prompt
and the agent's assistant text is returned unparsed, because DSPy adapters parse
their own ``[[ ## field ## ]]`` / JSON formats.

Sampling parameters (``temperature``, ``max_tokens``, …) have no CLI equivalent
and are ignored. ``n > 1`` runs the agent ``n`` times.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import dspy

from .adapter import CLIAgentAdapter

# "use tools" is deliberately not forbidden: a routing agent (e.g. vibe's
# notebooklm-assessment) answers by delegating through its ``task`` tool.
PREAMBLE = (
    "You are acting as a plain text-completion model for a DSPy program. "
    "Do not run commands, read or edit files, or browse. Answer only from the "
    "conversation below, and follow the output format it specifies exactly.\n\n"
)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
            else:
                parts.append("[non-text content omitted]")
        return "\n".join(parts)
    return "" if content is None else str(content)


def render_messages(prompt: str | None, messages: list[dict[str, Any]] | None) -> str:
    """Flatten chat ``messages`` (or a bare ``prompt``) into one agent prompt."""
    if not messages:
        return PREAMBLE + (prompt or "")
    sections = []
    for message in messages:
        role = str(message.get("role", "user")).capitalize()
        sections.append(f"### {role}\n{_content_text(message.get('content'))}")
    sections.append("### Assistant\n(Write only the next assistant message.)")
    return PREAMBLE + "\n\n".join(sections)


class CLIAgentLM(dspy.BaseLM):
    """``dspy.BaseLM`` that answers each request with one CLI agent run."""

    forward_contract = "legacy"

    def __init__(self, adapter: CLIAgentAdapter, **kwargs: Any) -> None:
        model = f"cli-agent/{adapter.name}" + (f"/{adapter.model}" if adapter.model else "")
        kwargs.setdefault("cache", False)
        super().__init__(model=model, model_type="chat", **kwargs)
        self.adapter = adapter

    def forward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        text_prompt = render_messages(prompt, messages)
        n = max(1, int(kwargs.get("n") or 1))
        choices = [
            SimpleNamespace(
                index=i,
                message=SimpleNamespace(content=self.adapter.complete(text_prompt)),
                finish_reason="stop",
            )
            for i in range(n)
        ]
        return SimpleNamespace(choices=choices, usage={}, model=self.model)

    async def aforward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Any:
        return await asyncio.to_thread(self.forward, prompt, messages, **kwargs)
