"""``sfl_tagging`` with the CLI-agent backend: engine resolution, batching, persistence."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import sfl_tagging
from notebooklm._app.scope import Scope
from notebooklm._app.sfl_tagging import (
    AmbiguousNotebookError,
    ChildRow,
    GroupProgress,
    default_engine,
    resolve_backend,
    resolve_corpus_notebook,
    run_tag_sfl,
    tag_children,
)
from notebooklm._preprocessing.cli_agents import (
    AgentResult,
    AgentSFLEngine,
    AgentTimeoutError,
    ClaudeAdapter,
    CLIAgentAdapter,
    OpenCodeAdapter,
)
from notebooklm.db.models import Clause
from tests._fixtures.corpus_seed import Seeder
from tests._fixtures.postgres import pg_session  # noqa: F401

ENV_VARS = (
    sfl_tagging.SFL_BACKEND_ENV,
    sfl_tagging.SFL_AGENT_MODEL_ENV,
    sfl_tagging.SFL_AGENT_TIMEOUT_ENV,
    sfl_tagging.SFL_AGENT_BATCH_ENV,
    sfl_tagging.SFL_AGENT_FALLBACK_ENV,
    sfl_tagging.SFL_AGENT_PROFILE_ENV,
    sfl_tagging.SFL_AGENT_WORKDIR_ENV,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


class FakeAdapter(CLIAgentAdapter):
    """Annotates every clause in a prompt; ``fail`` makes every call time out."""

    name = "fake"
    binary = "fake"

    def __init__(self, *, fail: bool = False) -> None:
        super().__init__(which=lambda _: "/bin/fake")
        self.fail = fail
        self.prompts = 0

    def build_argv(self, executable: str, prompt: str, schema: Any) -> list[str]:
        return [executable]

    def extract_text(self, stdout: str) -> str:
        return stdout

    def run(self, prompt: str, *, schema: Mapping[str, Any] | None = None) -> AgentResult:
        self.prompts += 1
        if self.fail:
            raise AgentTimeoutError(self.name, "timed out")
        clauses = json.loads(prompt.split("Clauses:\n", 1)[1])
        payload = {
            "annotations": [
                {
                    "index": c["index"],
                    "mood": "interrogative",
                    "modality": "none",
                    "tenor": "casual",
                }
                for c in clauses
            ]
        }
        return AgentResult(self.name, "", payload, "", 0.0)


def pass1(text: str) -> dict[str, Any]:
    return {"participants": [text], "processes": [], "circumstances": []}


def agent_engine(**kwargs: Any) -> tuple[AgentSFLEngine, FakeAdapter]:
    adapter = FakeAdapter(fail=kwargs.pop("fail", False))
    return AgentSFLEngine(adapter, pass1=pass1, **kwargs), adapter


def _row(id: int, parent_id: int, parent_index: int, text: str) -> ChildRow:
    return ChildRow(id=id, parent_id=parent_id, parent_index=parent_index, text=text)


CHILDREN = [_row(1, 10, 0, "a"), _row(2, 10, 0, "b"), _row(3, 11, 1, "c")]


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[int, int, int]] = []
        self.done: list[tuple[int, int, str | None]] = []
        self.saved: dict[int, dict[str, Any]] = {}

    def progress(self) -> GroupProgress:
        return GroupProgress(
            start=lambda n, total, idx, k: n,
            done=lambda h, k, f, e: self.done.append((k, f, e)),
            child=lambda d, t, p: self.events.append((d, t, p)),
        )

    async def save(self, session_factory: Any, values: dict[int, dict[str, Any]]) -> None:
        self.saved.update(values)


def _tag(engine: Any, rec: Recorder) -> tuple[int, int]:
    return asyncio.run(
        tag_children(
            CHILDREN,
            session_factory=None,  # type: ignore[arg-type] - save is faked
            progress=rec.progress(),
            engine=engine,
            lm=object(),
            save=rec.save,
        )
    )


# -- backend resolution --------------------------------------------------


def test_resolve_backend_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    assert resolve_backend() == "dspy"
    monkeypatch.setenv(sfl_tagging.SFL_BACKEND_ENV, " Claude ")
    assert resolve_backend() == "claude"
    assert resolve_backend("opencode") == "opencode"
    monkeypatch.setenv(sfl_tagging.SFL_BACKEND_ENV, "")
    assert resolve_backend() == "dspy"


def test_default_engine_reads_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sfl_tagging.SFL_BACKEND_ENV, "claude")
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_MODEL_ENV, "haiku")
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_TIMEOUT_ENV, "42")
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_BATCH_ENV, "0")
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_FALLBACK_ENV, "false")
    engine = default_engine()
    assert isinstance(engine, AgentSFLEngine)
    assert isinstance(engine.adapter, ClaudeAdapter)
    assert engine.adapter.model == "haiku" and engine.adapter.timeout == 42.0
    assert engine.batch is False and engine.fallback is False
    assert engine.adapter.agent == "sfl-annotator"  # default profile
    assert sfl_tagging.engine_backend(engine) == "agent:claude/sfl-annotator"


def test_default_engine_profile_and_workdir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_PROFILE_ENV, "my-annotator")
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_WORKDIR_ENV, "~/agents-home")
    engine = default_engine("opencode")
    assert engine.adapter.agent == "my-annotator"
    assert engine.adapter.workdir.endswith("/agents-home")
    assert not engine.adapter.workdir.startswith("~")
    assert default_engine("opencode", agent_profile="", workdir="/w").adapter.agent is None
    monkeypatch.setenv(sfl_tagging.SFL_AGENT_PROFILE_ENV, "")
    assert default_engine("claude").adapter.agent is None


def test_to_sfl_keeps_textual_metafunction_keys() -> None:
    sfl = sfl_tagging.to_sfl(
        {
            "ideational": {"participants": ["we"]},
            "interpersonal": {
                "mood": "declarative",
                "modality": "median",
                "tenor": "casual",
                "theme": "So we",
                "rheme": "should go",
                "cohesive_markers": ["So"],
                "extra": 1,
            },
            "backend": "agent:agy/sfl-annotator",
        }
    )
    assert sfl["theme"] == "So we" and sfl["rheme"] == "should go"
    assert sfl["cohesive_markers"] == ["So"]
    assert sfl["raw"] == {"extra": 1, "backend": "agent:agy/sfl-annotator"}
    # DSPy output without textual keys keeps the old shape.
    plain = sfl_tagging.to_sfl({"ideational": {}, "interpersonal": {"mood": "x"}})
    assert set(plain) == {"mood", "modality", "tenor", "pass1"}


def test_default_engine_arguments_override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sfl_tagging.SFL_BACKEND_ENV, "claude")
    engine = default_engine("opencode", model="m", timeout=5, batch=True, fallback=True)
    assert isinstance(engine.adapter, OpenCodeAdapter)
    assert (engine.adapter.model, engine.adapter.timeout) == ("m", 5)
    assert engine.batch and engine.fallback


def test_default_engine_dspy_backend_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = default_engine("dspy")
    assert type(engine).__name__ == "SFLEngine"
    assert sfl_tagging.engine_backend(engine) == "dspy"
    with pytest.raises(ValueError, match="unknown CLI agent"):
        default_engine("gpt")


# -- tag_children batching -------------------------------------------------


def test_tag_children_batches_each_parent_into_one_prompt() -> None:
    engine, adapter = agent_engine()
    rec = Recorder()
    assert _tag(engine, rec) == (3, 0)
    assert adapter.prompts == 2  # one per parent, not per clause
    assert rec.events == [(0, 3, 1), (2, 3, 1), (2, 3, 2), (3, 3, 2)]  # monotonic
    assert rec.saved[1]["mood"] == "interrogative"
    assert rec.saved[1]["pass1"] == {"participants": ["a"], "processes": [], "circumstances": []}
    assert rec.saved[1]["raw"] == {"backend": "agent:fake"}


def test_tag_children_without_batch_uses_per_child_forward() -> None:
    engine, adapter = agent_engine(batch=False)
    rec = Recorder()
    assert _tag(engine, rec) == (3, 0)
    assert adapter.prompts == 3
    assert [e[0] for e in rec.events] == [0, 1, 1, 2, 2, 3]


def test_tag_children_counts_agent_failures_without_fallback() -> None:
    engine, _ = agent_engine(fail=True, fallback=False)
    rec = Recorder()
    assert _tag(engine, rec) == (0, 3)
    assert rec.saved == {}
    assert rec.done[0][1] == 2 and "AgentTimeoutError" in str(rec.done[0][2])


def test_tag_children_records_dspy_fallback_provenance() -> None:
    class FakeDSPy:
        def forward(self, utterance: str) -> dict[str, Any]:
            return {"ideational": {}, "interpersonal": {"mood": "declarative", "tenor": "formal"}}

    adapter = FakeAdapter(fail=True)
    engine = AgentSFLEngine(adapter, pass1=pass1, fallback_factory=FakeDSPy)
    rec = Recorder()
    assert _tag(engine, rec) == (3, 0)
    assert rec.saved[3]["tenor"] == "formal"
    assert rec.saved[3]["raw"]["backend"] == "dspy-fallback"


def test_tag_children_wrong_result_count_fails_the_parent() -> None:
    class ShortEngine:
        batch = True

        def forward(self, text: str) -> dict[str, Any]:
            raise AssertionError("unused")

        def forward_batch(self, texts: list[str]) -> list[Any]:
            return []

    rec = Recorder()
    assert _tag(ShortEngine(), rec) == (0, 3)
    assert "engine returned 0 results" in str(rec.done[0][2])


def test_run_tag_sfl_reports_parents_and_handles_empty_scope() -> None:
    engine, _ = agent_engine()
    rec = Recorder()
    outcomes: list[tuple[int, int]] = []

    async def load(factory: Any, scope: Any) -> list[ChildRow]:
        return CHILDREN

    async def load_none(factory: Any, scope: Any) -> list[ChildRow]:
        return []

    report = asyncio.run(
        run_tag_sfl(
            "nb",
            session_factory=None,  # type: ignore[arg-type]
            engine=engine,
            lm=object(),
            on_parent=lambda n, total, o: outcomes.append((n, total)),
            load=load,
            save=rec.save,
            resolve_notebook=None,
        )
    )
    assert (report.children, report.tagged, report.failed) == (3, 3, 0)
    assert report.backend == "agent:fake"
    assert [p.parent_index for p in report.parents] == [0, 1]
    assert outcomes == [(1, 2), (2, 2)]

    empty = asyncio.run(
        run_tag_sfl(
            "nb",
            session_factory=None,
            engine=engine,
            load=load_none,
            resolve_notebook=None,
        )  # type: ignore[arg-type]
    )
    assert empty.children == 0 and empty.parents == []


# -- persistence -------------------------------------------------------------


class _SessionFactory:
    """``async_sessionmaker`` stand-in that reuses the rolled-back test session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __call__(self) -> Any:
        session = self.session

        class _Ctx:
            async def __aenter__(self) -> AsyncSession:
                return session

            async def __aexit__(self, *exc: object) -> None:
                return None

        return _Ctx()


@pytest.mark.asyncio
async def test_agent_tagging_persists_sfl_to_postgres(pg_session: AsyncSession) -> None:  # noqa: F811
    seeder = Seeder(pg_session)
    await seeder.ingest("doc", "one|two||three")
    factory = _SessionFactory(pg_session)
    engine, adapter = agent_engine()

    report = await run_tag_sfl(
        Scope(document_ids=(seeder.doc("doc"),)),
        session_factory=factory,  # type: ignore[arg-type]
        engine=engine,
        lm=object(),
    )

    assert (report.children, report.tagged, report.failed) == (3, 3, 0)
    assert adapter.prompts == 2
    rows = (
        await pg_session.execute(
            select(Clause.text, Clause.sfl).where(Clause.document_id == seeder.doc("doc"))
        )
    ).all()
    stored = dict(rows)
    assert set(stored) == {"one", "two", "three"}
    for text, sfl in stored.items():
        assert sfl["mood"] == "interrogative" and sfl["tenor"] == "casual"
        assert sfl["pass1"]["participants"] == [text]
        assert sfl["raw"] == {"backend": "agent:fake"}


@pytest.mark.asyncio
async def test_notebook_prefix_resolves_and_tags_that_notebook(
    pg_session: AsyncSession,  # noqa: F811
) -> None:
    seeder = Seeder(pg_session)
    await seeder.ingest("a", "alpha|beta")
    await seeder.ingest("b", "gamma", notebook=f"{seeder.notebook}-other")
    factory = _SessionFactory(pg_session)

    assert await resolve_corpus_notebook(factory, seeder.notebook) == seeder.notebook  # exact
    assert await resolve_corpus_notebook(factory, f"{seeder.notebook}-o") == (
        f"{seeder.notebook}-other"
    )
    assert await resolve_corpus_notebook(factory, "nb-does-not-exist-x") == "nb-does-not-exist-x"
    with pytest.raises(AmbiguousNotebookError) as info:
        await resolve_corpus_notebook(factory, seeder.notebook[:-2])
    assert info.value.candidates == [seeder.notebook, f"{seeder.notebook}-other"]

    engine, _ = agent_engine()
    report = await run_tag_sfl(
        f"{seeder.notebook}-o",
        session_factory=factory,  # type: ignore[arg-type]
        engine=engine,
        lm=object(),
    )
    assert (report.children, report.tagged) == (1, 1)
