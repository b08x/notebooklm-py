"""Doctor rows for the LLM CLI coding agents used as SFL backends."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path

import pytest

from notebooklm import paths
from notebooklm._app.doctor import DoctorPaths, cli_agent_checks, run_checks
from notebooklm._preprocessing.cli_agents import CompletedRun


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("NOTEBOOKLM_HOME", str(tmp_path))
    monkeypatch.delenv("NOTEBOOKLM_PROFILE", raising=False)
    monkeypatch.delenv("NOTEBOOKLM_AUTH_JSON", raising=False)
    paths.set_active_profile(None)
    paths._reset_config_cache()
    yield tmp_path
    paths.set_active_profile(None)
    paths._reset_config_cache()


def only_claude_and_vibe(name: str) -> str | None:
    return f"/opt/{name}" if name in ("claude", "vibe") else None


def version_runner(
    argv: Sequence[str], timeout: float, env: Mapping[str, str] | None
) -> CompletedRun:
    if argv[0] == "/opt/vibe":
        return CompletedRun(1, "", "boom")
    return CompletedRun(0, "2.1.300 (Claude Code)\n", "")


def test_cli_agent_checks_pass_with_version_and_warn_when_missing() -> None:
    rows = cli_agent_checks(which=only_claude_and_vibe, runner=version_runner)
    assert list(rows) == ["agent_claude", "agent_agy", "agent_vibe", "agent_opencode"]
    assert rows["agent_claude"] == {
        "status": "pass",
        "detail": "2.1.300 (Claude Code) (/opt/claude)",
    }
    assert rows["agent_vibe"] == {"status": "pass", "detail": "version unknown (/opt/vibe)"}
    assert rows["agent_agy"]["status"] == "warn"
    assert "'agy' not found on PATH" in rows["agent_agy"]["detail"]
    assert all(row["status"] != "fail" for row in rows.values())


def _paths(agent_checks: object) -> DoctorPaths:
    return DoctorPaths(
        get_path_info=paths.get_path_info,
        get_home_dir=paths.get_home_dir,
        get_profile_dir=paths.get_profile_dir,
        get_storage_path=paths.get_storage_path,
        get_config_path=paths.get_config_path,
        headless_reauth_check=lambda: {"status": "pass", "detail": "ok"},
        agent_checks=agent_checks,  # type: ignore[arg-type]
    )


def test_run_checks_includes_agent_rows_only_when_probe_given(home: Path) -> None:
    without = run_checks(fix=False, paths=_paths(None))
    assert not any(name.startswith("agent_") for name in without.checks)

    with_agents = run_checks(
        fix=False,
        paths=_paths(lambda: cli_agent_checks(which=lambda _: None, runner=version_runner)),
    )
    agent_rows = {k: v for k, v in with_agents.checks.items() if k.startswith("agent_")}
    assert len(agent_rows) == 4
    assert {row["status"] for row in agent_rows.values()} == {"warn"}
    # Missing optional agents never flip doctor's exit status on their own.
    assert with_agents.has_failures == without.has_failures


def test_probe_exception_degrades_to_warn() -> None:
    def broken_which(name: str) -> str | None:
        raise AttributeError("platform quirk")

    rows = cli_agent_checks(which=broken_which, runner=version_runner)
    assert len(rows) == 4
    assert all(row["status"] == "warn" for row in rows.values())
    assert "probe failed (AttributeError: platform quirk)" in rows["agent_claude"]["detail"]
