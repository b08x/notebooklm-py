"""CLI agent adapters run against a recording fake subprocess runner.

The stdout fixtures reproduce the envelopes each real CLI printed for the
prompt ``Reply with only this JSON: {"ok": true}``.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping, Sequence

import pytest

from notebooklm._preprocessing.cli_agents import (
    AGENT_NAMES,
    AgentCommandError,
    AgentNotFoundError,
    AgentParseError,
    AgentTimeoutError,
    AgyAdapter,
    ClaudeAdapter,
    CompletedRun,
    OpenCodeAdapter,
    UnknownAgentError,
    VibeAdapter,
    agent_status,
    get_adapter,
    probe_agents,
)

CLAUDE_OUT = json.dumps(
    {"type": "result", "subtype": "success", "is_error": False, "result": '{"ok": true}'}
)
AGY_OUT = json.dumps({"conversation_id": "c", "status": "SUCCESS", "response": '{"ok": true}\n'})
VIBE_OUT = json.dumps(
    [
        {"type": "message", "role": "user", "content": [{"type": "text", "text": "prompt"}]},
        {"type": "reasoning", "text": "thinking"},
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "text", "text": '{"ok": true}'}],
        },
    ]
)
OPENCODE_OUT = "\n".join(
    json.dumps(e)
    for e in (
        {"type": "step_start", "part": {"type": "step-start"}},
        {"type": "text", "part": {"type": "text", "text": '{"ok": '}},
        {"type": "text", "part": {"type": "text", "text": "true}"}},
        {"type": "step_finish", "part": {"type": "step-finish"}},
    )
)


class FakeRunner:
    def __init__(
        self,
        stdout: str = "",
        *,
        returncode: int = 0,
        stderr: str = "",
        exc: Exception | None = None,
    ) -> None:
        self.stdout, self.returncode, self.stderr, self.exc = stdout, returncode, stderr, exc
        self.calls: list[tuple[list[str], float, Mapping[str, str] | None]] = []

    def __call__(
        self, argv: Sequence[str], timeout: float, env: Mapping[str, str] | None
    ) -> CompletedRun:
        self.calls.append((list(argv), timeout, env))
        if self.exc is not None:
            raise self.exc
        return CompletedRun(self.returncode, self.stdout, self.stderr)


def which_all(name: str) -> str | None:
    return f"/usr/bin/{name}"


def which_none(name: str) -> str | None:
    return None


SCHEMA = {"type": "object"}


@pytest.mark.parametrize(
    ("cls", "stdout"),
    [
        (ClaudeAdapter, CLAUDE_OUT),
        (AgyAdapter, AGY_OUT),
        (VibeAdapter, VIBE_OUT),
        (OpenCodeAdapter, OPENCODE_OUT),
    ],
)
def test_each_adapter_parses_its_real_envelope(
    cls: type, stdout: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    runner = FakeRunner(stdout)
    result = cls(runner=runner, which=which_all, timeout=12).run("PROMPT", schema=SCHEMA)
    assert result.payload == {"ok": True}
    assert result.agent == cls.name
    argv, timeout, env = runner.calls[0]
    assert argv[0] == f"/usr/bin/{cls.binary}"
    assert "PROMPT" in argv
    assert timeout == 12
    inherited = env is None  # bool, so a failure never prints the environment
    assert inherited, "env should be inherited unchanged"


def test_claude_argv_has_print_json_schema_and_model() -> None:
    runner = FakeRunner(CLAUDE_OUT)
    ClaudeAdapter(runner=runner, which=which_all, model="haiku", extra_args=["--x"]).run(
        "P", schema=SCHEMA
    )
    assert runner.calls[0][0] == [
        "/usr/bin/claude",
        "-p",
        "P",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(SCHEMA),
        "--model",
        "haiku",
        "--x",
    ]


def test_claude_prefers_structured_output() -> None:
    out = json.dumps(
        {"type": "result", "subtype": "success", "result": "prose", "structured_output": {"a": 1}}
    )
    result = ClaudeAdapter(runner=FakeRunner(out), which=which_all).run("P", schema=SCHEMA)
    assert result.payload == {"a": 1}


def test_claude_is_error_envelope_raises_command_error() -> None:
    out = json.dumps({"type": "result", "subtype": "success", "is_error": True, "result": "quota"})
    with pytest.raises(AgentCommandError, match="quota"):
        ClaudeAdapter(runner=FakeRunner(out), which=which_all).run("P")


def test_agy_argv_and_failed_status() -> None:
    runner = FakeRunner(AGY_OUT)
    AgyAdapter(runner=runner, which=which_all, model="m").run("P", schema=SCHEMA)
    assert runner.calls[0][0] == [
        "/usr/bin/agy",
        "-p",
        "P",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(SCHEMA),
        "--model",
        "m",
    ]
    bad = json.dumps({"status": "FAILED", "error": "auth expired"})
    with pytest.raises(AgentCommandError, match="auth expired"):
        AgyAdapter(runner=FakeRunner(bad), which=which_all).run("P")


def test_vibe_argv_ignores_schema_and_model() -> None:
    runner = FakeRunner(VIBE_OUT)
    VibeAdapter(runner=runner, which=which_all, model="ignored").run("P", schema=SCHEMA)
    assert runner.calls[0][0] == ["/usr/bin/vibe", "-p", "P", "--output", "json"]


def test_vibe_without_assistant_message_raises_parse_error() -> None:
    out = json.dumps([{"type": "message", "role": "user", "content": "hi"}])
    with pytest.raises(AgentParseError):
        VibeAdapter(runner=FakeRunner(out), which=which_all).run("P")


def test_opencode_argv_puts_prompt_after_double_dash() -> None:
    runner = FakeRunner(OPENCODE_OUT)
    OpenCodeAdapter(runner=runner, which=which_all, model="anthropic/x").run("-P", schema=SCHEMA)
    assert runner.calls[0][0] == [
        "/usr/bin/opencode",
        "run",
        "--format",
        "json",
        "-m",
        "anthropic/x",
        "--",
        "-P",
    ]


def test_opencode_error_event_raises() -> None:
    out = json.dumps({"type": "error", "error": {"message": "no provider"}})
    with pytest.raises(AgentCommandError, match="no provider"):
        OpenCodeAdapter(runner=FakeRunner(out), which=which_all).run("P")


def test_env_overrides_are_merged_into_process_env() -> None:
    runner = FakeRunner(CLAUDE_OUT)
    ClaudeAdapter(runner=runner, which=which_all, env={"FOO": "bar"}).run("P")
    env = runner.calls[0][2]
    assert env is not None and env["FOO"] == "bar" and "PATH" in env


def test_missing_binary_raises_not_found_without_running() -> None:
    runner = FakeRunner(CLAUDE_OUT)
    with pytest.raises(AgentNotFoundError):
        ClaudeAdapter(runner=runner, which=which_none).run("P")
    assert runner.calls == []


def test_timeout_maps_to_agent_timeout_error() -> None:
    runner = FakeRunner(exc=subprocess.TimeoutExpired(["claude"], 5))
    with pytest.raises(AgentTimeoutError, match="timed out"):
        ClaudeAdapter(runner=runner, which=which_all, timeout=5).run("P")


def test_os_error_maps_to_command_error() -> None:
    with pytest.raises(AgentCommandError, match="failed to start"):
        ClaudeAdapter(runner=FakeRunner(exc=OSError("denied")), which=which_all).run("P")


def test_nonzero_exit_raises_command_error_with_stderr() -> None:
    runner = FakeRunner("", returncode=2, stderr="line1\nfatal: not logged in")
    with pytest.raises(AgentCommandError, match="not logged in") as info:
        AgyAdapter(runner=runner, which=which_all).run("P")
    assert info.value.returncode == 2


def test_unparseable_answer_raises_parse_error() -> None:
    out = json.dumps({"status": "SUCCESS", "response": "I cannot do that."})
    with pytest.raises(AgentParseError):
        AgyAdapter(runner=FakeRunner(out), which=which_all).run("P")


def test_registry_lookup_is_case_insensitive_and_rejects_unknown() -> None:
    assert AGENT_NAMES == ("claude", "agy", "vibe", "opencode")
    assert isinstance(get_adapter(" Claude "), ClaudeAdapter)
    with pytest.raises(UnknownAgentError, match="expected one of"):
        get_adapter("gpt")


def test_version_probe_and_status() -> None:
    runner = FakeRunner("2.1.300 (Claude Code)\n")
    status = agent_status("claude", which=which_all, runner=runner)
    assert status.available and status.version == "2.1.300 (Claude Code)"
    assert runner.calls[0][0] == ["/usr/bin/claude", "--version"]

    failing = FakeRunner("", returncode=1)
    assert agent_status("agy", which=which_all, runner=failing).version is None
    timeout = FakeRunner(exc=subprocess.TimeoutExpired(["vibe"], 1))
    assert agent_status("vibe", which=which_all, runner=timeout).version is None


def test_probe_agents_reports_missing_binaries_without_spawning() -> None:
    runner = FakeRunner("x")
    statuses = probe_agents(which=which_none, runner=runner)
    assert [s.name for s in statuses] == list(AGENT_NAMES)
    assert not any(s.available for s in statuses)
    assert runner.calls == []


@pytest.mark.parametrize(
    ("cls", "stdout", "expected_tail"),
    [
        (ClaudeAdapter, CLAUDE_OUT, ["--agent", "sfl-annotator"]),
        (AgyAdapter, AGY_OUT, ["--agent", "sfl-annotator"]),
        (VibeAdapter, VIBE_OUT, ["--agent", "sfl-annotator", "--workdir", "/w"]),
        (OpenCodeAdapter, OPENCODE_OUT, ["--agent", "sfl-annotator", "--dir", "/w"]),
    ],
)
def test_named_agent_and_workdir_flags(cls: type, stdout: str, expected_tail: list[str]) -> None:
    runner = FakeRunner(stdout)
    cls(runner=runner, which=which_all, agent="sfl-annotator", workdir="/w").run("P")
    argv = runner.calls[0][0]
    if cls is OpenCodeAdapter:
        argv = argv[: argv.index("--")]
    assert argv[-len(expected_tail) :] == expected_tail
    if cls in (ClaudeAdapter, AgyAdapter):
        assert "/w" not in argv  # no project-agent directory flag for these CLIs


def test_no_agent_flag_by_default() -> None:
    runner = FakeRunner(CLAUDE_OUT)
    ClaudeAdapter(runner=runner, which=which_all, agent="").run("P")
    assert "--agent" not in runner.calls[0][0]


def test_claude_child_env_drops_api_key_so_subscription_login_is_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "tok")
    monkeypatch.delenv("NOTEBOOKLM_CLAUDE_USE_API_KEY", raising=False)
    runner = FakeRunner(CLAUDE_OUT)
    ClaudeAdapter(runner=runner, which=which_all, env={"FOO": "1"}).run("P")
    env = runner.calls[0][2]
    assert env is not None
    stripped = "ANTHROPIC_API_KEY" not in env and "ANTHROPIC_AUTH_TOKEN" not in env
    assert stripped, "API-key variables must not reach the claude child process"
    assert env["FOO"] == "1"
    assert "PATH" in env


def test_claude_api_key_kept_when_opted_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("NOTEBOOKLM_CLAUDE_USE_API_KEY", "1")
    runner = FakeRunner(CLAUDE_OUT)
    ClaudeAdapter(runner=runner, which=which_all).run("P")
    inherited = runner.calls[0][2] is None  # bool: never print the environment
    assert inherited, "env should be inherited unchanged"


def test_other_agents_inherit_environment_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    runner = FakeRunner(AGY_OUT)
    AgyAdapter(runner=runner, which=which_all).run("P")
    inherited = runner.calls[0][2] is None  # bool: never print the environment
    assert inherited, "env should be inherited unchanged"
