"""``CLIAgentLM`` (DSPy LM over a CLI agent) and assessment-router selection."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator, Mapping, Sequence

import dspy
import pytest

from notebooklm._app import assessment
from notebooklm._preprocessing.cli_agents import (
    AgentTimeoutError,
    AgyAdapter,
    ClaudeAdapter,
    CompletedRun,
    OpenCodeAdapter,
)
from notebooklm._preprocessing.cli_agents.dspy_lm import PREAMBLE, CLIAgentLM, render_messages


class AgyRunner:
    """Answers every prompt with ``reply`` inside agy's JSON envelope."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []
        self.argvs: list[list[str]] = []

    def __call__(
        self, argv: Sequence[str], timeout: float, env: Mapping[str, str] | None
    ) -> CompletedRun:
        self.prompts.append(argv[argv.index("-p") + 1])
        self.argvs.append(list(argv))
        assert "--json-schema" not in argv  # free-text completion, no schema
        return CompletedRun(0, json.dumps({"status": "SUCCESS", "response": self.reply}), "")


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


def test_complete_returns_raw_text_without_json_parsing() -> None:
    runner = AgyRunner("plain prose, not JSON")
    adapter = AgyAdapter(runner=runner, which=which_all)
    assert adapter.complete("hello") == "plain prose, not JSON"


def test_render_messages_flattens_roles_and_content_parts() -> None:
    text = render_messages(
        None,
        [
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": [{"type": "text", "text": "Hi"}, {"type": "image_url"}]},
            {"role": "assistant", "content": "Hello"},
            {"role": "user", "content": "Again"},
        ],
    )
    assert text.startswith(PREAMBLE)
    assert "### System\nBe terse." in text
    assert "### User\nHi\n[non-text content omitted]" in text
    assert "### Assistant\nHello" in text
    assert text.endswith("### Assistant\n(Write only the next assistant message.)")
    assert render_messages("bare prompt", None) == PREAMBLE + "bare prompt"


def test_lm_drives_a_dspy_predict_program() -> None:
    runner = AgyRunner("[[ ## answer ## ]]\nParis\n\n[[ ## completed ## ]]")
    lm = CLIAgentLM(AgyAdapter(runner=runner, which=which_all, model="m"))
    assert lm.model == "cli-agent/agy/m"
    with dspy.context(lm=lm):
        result = dspy.Predict("question -> answer")(question="Capital of France?")
    assert result.answer == "Paris"
    assert "Capital of France?" in runner.prompts[0]


def test_lm_n_runs_agent_n_times_and_async_forward() -> None:
    runner = AgyRunner("x")
    lm = CLIAgentLM(AgyAdapter(runner=runner, which=which_all))
    response = lm.forward(prompt="p", n=3)
    assert [c.message.content for c in response.choices] == ["x", "x", "x"]
    assert len(runner.prompts) == 3
    async_response = asyncio.run(lm.aforward(messages=[{"role": "user", "content": "q"}]))
    assert async_response.choices[0].message.content == "x"


def test_lm_propagates_agent_errors() -> None:
    def timeout_runner(argv: Sequence[str], timeout: float, env: object) -> CompletedRun:
        raise __import__("subprocess").TimeoutExpired(argv, timeout)

    lm = CLIAgentLM(AgyAdapter(runner=timeout_runner, which=which_all, timeout=1))
    with pytest.raises(AgentTimeoutError):
        lm.forward(prompt="p")


# -- setup_dspy_router provider selection ------------------------------------


@pytest.fixture
def no_langfuse(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clean env, and restore the global DSPy LM the router configures."""
    previous = dspy.settings.lm
    for name in (
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "NOTEBOOKLM_ASSESSMENT_MODEL",
        assessment.ASSESSMENT_AGENT_TIMEOUT_ENV,
        assessment.ASSESSMENT_AGENT_PROFILE_ENV,
    ):
        monkeypatch.delenv(name, raising=False)
    yield
    dspy.settings.configure(lm=previous)


def test_router_builds_agent_lm_for_agent_provider(
    monkeypatch: pytest.MonkeyPatch, no_langfuse: None
) -> None:
    monkeypatch.setenv("NOTEBOOKLM_ASSESSMENT_MODEL_PROVIDER", "Claude")
    monkeypatch.setenv(assessment.ASSESSMENT_AGENT_TIMEOUT_ENV, "77")
    lm, _ = assessment.setup_dspy_router()
    assert isinstance(lm, CLIAgentLM)
    assert isinstance(lm.adapter, ClaudeAdapter)
    # The OpenRouter default model is not forwarded to the agent.
    assert lm.adapter.model is None and lm.adapter.timeout == 77.0
    assert lm.model == "cli-agent/claude"


def test_router_passes_assessment_model_to_agent(
    monkeypatch: pytest.MonkeyPatch, no_langfuse: None
) -> None:
    monkeypatch.setenv("NOTEBOOKLM_ASSESSMENT_MODEL_PROVIDER", "opencode")
    monkeypatch.setenv("NOTEBOOKLM_ASSESSMENT_MODEL", "anthropic/claude-haiku-5-5")
    lm = assessment.build_agent_lm("opencode", "anthropic/claude-haiku-5-5")
    assert isinstance(lm.adapter, OpenCodeAdapter)
    assert lm.adapter.model == "anthropic/claude-haiku-5-5"


def test_router_keeps_litellm_for_http_providers(
    monkeypatch: pytest.MonkeyPatch, no_langfuse: None
) -> None:
    monkeypatch.setenv("NOTEBOOKLM_ASSESSMENT_MODEL_PROVIDER", "openrouter")
    lm, _ = assessment.setup_dspy_router()
    assert not isinstance(lm, CLIAgentLM)
    assert lm.model == f"openrouter/{assessment.DEFAULT_MODEL}"


def test_assessment_agent_profile_default_env_and_empty(
    monkeypatch: pytest.MonkeyPatch, no_langfuse: None
) -> None:
    lm = assessment.build_agent_lm("vibe")
    assert lm.adapter.agent == "notebooklm-assessment"  # default profile
    assert lm.model == "cli-agent/vibe"

    monkeypatch.setenv(assessment.ASSESSMENT_AGENT_PROFILE_ENV, "my-assessor")
    assert assessment.build_agent_lm("claude").adapter.agent == "my-assessor"
    assert assessment.build_agent_lm("claude", agent_profile="x").adapter.agent == "x"

    monkeypatch.setenv(assessment.ASSESSMENT_AGENT_PROFILE_ENV, "")
    assert assessment.build_agent_lm("claude").adapter.agent is None


def test_assessment_agent_profile_reaches_cli_argv(
    monkeypatch: pytest.MonkeyPatch, no_langfuse: None
) -> None:
    runner = AgyRunner("ok")
    lm = CLIAgentLM(AgyAdapter(runner=runner, which=which_all, agent="notebooklm-assessment"))
    lm.forward(prompt="p")
    assert runner.argvs[0][-2:] == ["--agent", "notebooklm-assessment"]


def test_preamble_does_not_forbid_delegation_tools() -> None:
    # A routing agent must still be able to call its delegation tool.
    assert "use tools" not in PREAMBLE
    assert "Do not run commands, read or edit files, or browse." in PREAMBLE
