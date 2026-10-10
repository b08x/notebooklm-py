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

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

import httpx
from opentelemetry import trace

logger = logging.getLogger(__name__)

DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_JEV_MODEL = "typesafe/jev-1.13"
_EXCERPT_CHARS = 500
_SPAN_ATTR_CHARS = 4000


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
    """Calls the Jev decisions endpoint and parses one :class:`Decision` per question.

    Retries 429 and 5xx responses with exponential backoff. Each call opens the
    ``jev.decision`` span with the request state and the response body.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_JEV_MODEL,
        url: str = DECISIONS_URL,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.url = url
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self._http_client = http_client

    async def decide(
        self, state: dict[str, Any], questions: dict[str, ChoiceQuestion]
    ) -> dict[str, Decision]:
        api_key = self.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            raise JevError("OPENROUTER_API_KEY is not set; Jev decisions need it")

        payload = {
            "model": self.model,
            "state": state,
            "questions": {
                name: {"type": "choice", "instructions": q.instructions, "criteria": q.criteria}
                for name, q in questions.items()
            },
        }
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("jev.decision") as span:
            span.set_attribute("jev.model", self.model)
            span.set_attribute("jev.state", json.dumps(state, default=str)[:_SPAN_ATTR_CHARS])

            body = await self._post(payload, api_key)
            span.set_attribute("jev.response", json.dumps(body, default=str)[:_SPAN_ATTR_CHARS])

            decisions = {name: self._parse(name, body) for name in questions}
            span.set_attribute(
                "jev.choice", json.dumps({n: d.choice for n, d in decisions.items()})
            )
            span.set_attribute(
                "jev.confidence", json.dumps({n: d.confidence for n, d in decisions.items()})
            )
        return decisions

    async def _post(self, payload: dict[str, Any], api_key: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key}"}
        client = self._http_client or httpx.AsyncClient(timeout=self.timeout)
        try:
            for attempt in range(self.max_retries + 1):
                resp = await client.post(self.url, json=payload, headers=headers)
                retryable = resp.status_code == 429 or resp.status_code >= 500
                if retryable and attempt < self.max_retries:
                    delay = self.backoff_base * (2**attempt)
                    logger.warning(f"Jev returned {resp.status_code}; retrying in {delay}s")
                    await asyncio.sleep(delay)
                    continue
                if resp.status_code >= 400:
                    raise JevError(
                        f"Jev request failed with HTTP {resp.status_code}: "
                        f"{resp.text[:_EXCERPT_CHARS]}"
                    )
                try:
                    body = resp.json()
                except ValueError as e:
                    raise JevError(
                        f"Jev returned a non-JSON body: {resp.text[:_EXCERPT_CHARS]}"
                    ) from e
                if not isinstance(body, dict):
                    raise JevError(f"Jev returned a non-object body: {str(body)[:_EXCERPT_CHARS]}")
                return body
        finally:
            if self._http_client is None:
                await client.aclose()
        raise JevError("Jev retries exhausted")  # pragma: no cover

    @staticmethod
    def _parse(name: str, body: dict[str, Any]) -> Decision:
        entry: Any = None
        for key in ("decisions", "results"):
            container = body.get(key)
            if isinstance(container, dict) and name in container:
                entry = container[name]
                break
        if entry is None:
            entry = body.get(name)
        if not isinstance(entry, dict) or "choice" not in entry:
            raise JevError(
                f"Jev response has no choice for question {name!r}: "
                f"{json.dumps(body, default=str)[:_EXCERPT_CHARS]}"
            )
        probabilities = entry.get("probabilities") or {}
        return Decision(
            choice=str(entry["choice"]),
            confidence=float(entry.get("confidence") or 0.0),
            probabilities={str(k): float(v) for k, v in probabilities.items()},
            raw=body,
        )
