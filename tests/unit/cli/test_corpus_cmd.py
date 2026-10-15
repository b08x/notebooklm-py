"""``notebooklm corpus tag-sfl``: scope building, backend selection, output."""

from __future__ import annotations

import json
from typing import Any

import pytest
from click.testing import CliRunner

from notebooklm._app.sfl_tagging import AmbiguousNotebookError, ParentOutcome, TagSFLReport
from notebooklm.cli import corpus_cmd
from notebooklm.notebooklm_cli import cli


class Spy:
    """Stands in for ``run_tag_sfl``; records the scope and engine it got."""

    def __init__(self, report: TagSFLReport) -> None:
        self.report = report
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, scope: Any, **kwargs: Any) -> TagSFLReport:
        self.calls.append({"scope": scope, **kwargs})
        on_parent = kwargs.get("on_parent")
        for number, outcome in enumerate(self.report.parents, start=1):
            if on_parent is not None:
                on_parent(number, len(self.report.parents), outcome)
        return self.report


def _report(tagged: int = 3, failed: int = 0, children: int = 3) -> TagSFLReport:
    parents = [
        ParentOutcome(0, 2, 0, None),
        ParentOutcome(1, 1, failed, "boom" if failed else None),
    ]
    return TagSFLReport(
        backend="agent:claude",
        children=children,
        parents=parents if children else [],
        tagged=tagged,
        failed=failed,
    )


@pytest.fixture
def spy(monkeypatch: pytest.MonkeyPatch) -> Spy:
    for name in (
        "NOTEBOOKLM_SFL_BACKEND",
        "NOTEBOOKLM_NOTEBOOK",
        "NOTEBOOKLM_SFL_AGENT_PROFILE",
        "NOTEBOOKLM_SFL_AGENT_WORKDIR",
    ):
        monkeypatch.delenv(name, raising=False)
    s = Spy(_report())
    monkeypatch.setattr(corpus_cmd, "run_tag_sfl", s)
    return s


def test_tag_sfl_document_scope_with_agent_json(spy: Spy) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "corpus",
            "tag-sfl",
            "--document",
            "d1",
            "--document",
            "d2",
            "--parent",
            "4",
            "--agent",
            "claude",
            "--model",
            "haiku",
            "--timeout",
            "30",
            "--no-batch",
            "--no-fallback",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "ok"
    assert payload["backend"] == "agent:claude"  # from the spied report
    assert payload["scope"]["document_ids"] == ["d1", "d2"]
    assert payload["scope"]["parent_id"] == 4
    assert (payload["children"], payload["parents"], payload["tagged"]) == (3, 2, 3)

    call = spy.calls[0]
    assert call["scope"].document_ids == ("d1", "d2") and call["scope"].notebook_id is None
    engine = call["engine"]
    assert engine.backend == "agent:claude/sfl-annotator"
    assert engine.adapter.model == "haiku" and engine.adapter.timeout == 30
    assert engine.batch is False and engine.fallback is False
    assert call["lm"] is None  # no DSPy LM needed when fallback is off


def test_tag_sfl_notebook_scope_text_output(spy: Spy) -> None:
    spy.report = _report(tagged=2, failed=1)
    result = CliRunner().invoke(
        cli, ["corpus", "tag-sfl", "-n", "nb-1", "--agent", "opencode", "--no-fallback"]
    )
    assert result.exit_code == 0, result.output
    assert spy.calls[0]["scope"].notebook_id == "nb-1"
    assert "SFL backend: opencode" in result.output
    assert "1 failed — boom" in result.output
    assert "Tagged 2/3 clauses across 2 parents (1 failed)" in result.output


def test_tag_sfl_partial_json_lists_errors(spy: Spy) -> None:
    spy.report = _report(tagged=2, failed=1)
    result = CliRunner().invoke(
        cli, ["corpus", "tag-sfl", "--run", "7", "--agent", "agy", "--no-fallback", "--json"]
    )
    payload = json.loads(result.output)
    assert payload["status"] == "partial"
    assert payload["scope"]["run_ids"] == [7]
    assert payload["errors"] == [{"parent_index": 1, "failed": 1, "first_error": "boom"}]


def test_tag_sfl_backend_from_env(spy: Spy, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOTEBOOKLM_SFL_BACKEND", "vibe")
    result = CliRunner().invoke(cli, ["corpus", "tag-sfl", "--chunk", "c1", "--no-fallback"])
    assert result.exit_code == 0, result.output
    assert spy.calls[0]["engine"].backend == "agent:vibe/sfl-annotator"
    assert spy.calls[0]["scope"].external_ids == ("c1",)


def test_tag_sfl_no_clauses_is_an_error(spy: Spy) -> None:
    spy.report = _report(tagged=0, children=0)
    result = CliRunner().invoke(
        cli,
        ["corpus", "tag-sfl", "--document", "d", "--agent", "claude", "--no-fallback", "--json"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["code"] == "NO_CLAUSES"


def test_tag_sfl_all_failed_exits_nonzero(spy: Spy) -> None:
    spy.report = _report(tagged=0, failed=3)
    result = CliRunner().invoke(
        cli,
        ["corpus", "tag-sfl", "--document", "d", "--agent", "claude", "--no-fallback", "--json"],
    )
    assert result.exit_code == 1
    assert json.loads(result.output)["failed"] == 3


def test_tag_sfl_rejects_unknown_agent(spy: Spy) -> None:
    result = CliRunner().invoke(cli, ["corpus", "tag-sfl", "--document", "d", "--agent", "gpt"])
    assert result.exit_code == 2
    assert spy.calls == []


def test_tag_sfl_invalid_env_backend_reports_error(
    spy: Spy, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NOTEBOOKLM_SFL_BACKEND", "gpt")
    result = CliRunner().invoke(cli, ["corpus", "tag-sfl", "--document", "d", "--json"])
    assert result.exit_code == 2
    assert json.loads(result.output)["code"] == "INVALID_BACKEND"
    assert spy.calls == []


def test_tag_sfl_ambiguous_notebook_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ambiguous(scope: Any, **kwargs: Any) -> TagSFLReport:
        raise AmbiguousNotebookError("nb", ["nb-1", "nb-2"])

    monkeypatch.setattr(corpus_cmd, "run_tag_sfl", ambiguous)
    result = CliRunner().invoke(
        cli, ["corpus", "tag-sfl", "-n", "nb", "--agent", "claude", "--no-fallback", "--json"]
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["code"] == "AMBIGUOUS_ID"
    assert payload["candidates"] == ["nb-1", "nb-2"]


def test_tag_sfl_agent_profile_and_workdir_options(spy: Spy) -> None:
    result = CliRunner().invoke(
        cli,
        [
            "corpus",
            "tag-sfl",
            "--document",
            "d",
            "--agent",
            "opencode",
            "--agent-profile",
            "custom",
            "--agent-workdir",
            "/agents",
            "--no-fallback",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    adapter = spy.calls[0]["engine"].adapter
    assert (adapter.agent, adapter.workdir) == ("custom", "/agents")

    result = CliRunner().invoke(
        cli,
        [
            "corpus",
            "tag-sfl",
            "--document",
            "d",
            "--agent",
            "agy",
            "--agent-profile",
            "",
            "--no-fallback",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert spy.calls[1]["engine"].adapter.agent is None
