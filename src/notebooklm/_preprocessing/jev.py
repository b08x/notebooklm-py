"""Client for OpenRouter's Decisions API with the Jev decision model.

Jev returns a typed choice with a confidence and a probability per label instead
of generated text. Used for the 3-way fact-check verdict. The endpoint is alpha
(``/api/alpha/decisions``), so every call goes through this one module.

Request shape (per OpenRouter's Jev cookbook)::

    POST https://openrouter.ai/api/alpha/decisions
    {"model": "typesafe/jev-1.13",
     "state": {...any JSON...},
     "questions": {"verdict": {"type": "choice",
                               "instructions": "...",
                               "criteria": {"supported": "...", ...}}}}

Response: per question, ``choice``, ``confidence``, ``probabilities``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"


@dataclass
class ChoiceQuestion:
    instructions: str
    #: label -> plain-language criterion for choosing it.
    criteria: dict[str, str]


@dataclass
class Decision:
    choice: str
    confidence: float
    probabilities: dict[str, float] = field(default_factory=dict)
    #: Raw response body for the trace span / debugging.
    raw: dict[str, Any] = field(default_factory=dict)


class JevError(RuntimeError):
    pass


class JevClient:
    """Stub signature — implemented in wave 1 (agent ⑥).

    ``decide`` must: POST the request above with ``Authorization: Bearer
    $OPENROUTER_API_KEY``; retry 429/5xx with backoff; open an OTel child span
    ``jev.decision`` carrying the state and response; return one
    :class:`Decision` per question name.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_JEV_MODEL,
        url: str = DECISIONS_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries

    async def decide(
        self, state: dict[str, Any], questions: dict[str, ChoiceQuestion]
    ) -> dict[str, Decision]:
        raise NotImplementedError("JevClient.decide not implemented yet")
