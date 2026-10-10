import json

import httpx
import pytest

from notebooklm._preprocessing.jev import (
    DEFAULT_JEV_MODEL,
    ChoiceQuestion,
    JevClient,
    JevError,
)

VERDICT_Q = ChoiceQuestion(
    instructions="Decide the verdict.",
    criteria={"supported": "backed", "contradicted": "refuted", "unverifiable": "unclear"},
)

RECORDED_DECISION = {
    "choice": "contradicted",
    "confidence": 0.87,
    "probabilities": {"supported": 0.05, "contradicted": 0.87, "unverifiable": 0.08},
}


def _client(handler, **kwargs) -> JevClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return JevClient(api_key="test-key", http_client=http, backoff_base=0.0, **kwargs)


async def test_request_body_carries_model_state_and_criteria():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"decisions": {"verdict": RECORDED_DECISION}})

    state = {"claim": "c", "parent_context": "p", "sift_steps": {}, "citations": []}
    await _client(handler).decide(state, {"verdict": VERDICT_Q})

    assert seen["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert seen["auth"] == "Bearer test-key"
    body = seen["body"]
    assert body["model"] == DEFAULT_JEV_MODEL
    assert body["state"] == state
    assert body["questions"] == {
        "verdict": {
            "type": "choice",
            "instructions": "Decide the verdict.",
            "criteria": {
                "supported": "backed",
                "contradicted": "refuted",
                "unverifiable": "unclear",
            },
        }
    }


@pytest.mark.parametrize(
    "envelope",
    [
        lambda d: {"decisions": {"verdict": d}},
        lambda d: {"results": {"verdict": d}},
        lambda d: {"verdict": d},
    ],
)
async def test_parses_recorded_response_shapes(envelope):
    client = _client(lambda req: httpx.Response(200, json=envelope(RECORDED_DECISION)))

    decisions = await client.decide({"claim": "c"}, {"verdict": VERDICT_Q})

    decision = decisions["verdict"]
    assert decision.choice == "contradicted"
    assert decision.confidence == pytest.approx(0.87)
    assert decision.probabilities == pytest.approx(RECORDED_DECISION["probabilities"])


async def test_retries_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"verdict": RECORDED_DECISION})

    decisions = await _client(handler).decide({"claim": "c"}, {"verdict": VERDICT_Q})

    assert calls["n"] == 2
    assert decisions["verdict"].choice == "contradicted"


async def test_gives_up_after_max_retries_on_5xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="unavailable")

    with pytest.raises(JevError, match="503"):
        await _client(handler, max_retries=2).decide({"claim": "c"}, {"verdict": VERDICT_Q})
    assert calls["n"] == 3


async def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    client = JevClient(
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: pytest.fail("no request expected"))
        )
    )

    with pytest.raises(JevError, match="OPENROUTER_API_KEY"):
        await client.decide({"claim": "c"}, {"verdict": VERDICT_Q})


async def test_env_api_key_is_used(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers["Authorization"]
        return httpx.Response(200, json={"verdict": RECORDED_DECISION})

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await JevClient(http_client=http).decide({"claim": "c"}, {"verdict": VERDICT_Q})

    assert seen["auth"] == "Bearer env-key"


async def test_response_without_choice_raises_with_body_excerpt():
    client = _client(lambda req: httpx.Response(200, json={"unexpected": {"foo": "bar-body"}}))

    with pytest.raises(JevError, match="bar-body"):
        await client.decide({"claim": "c"}, {"verdict": VERDICT_Q})
