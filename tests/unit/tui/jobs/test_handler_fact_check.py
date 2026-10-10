"""``fact_check`` handler tests with injected fakes (no Redis, no Postgres).

The job store is a dict-backed fake, the DB session records ORM adds and
executed statements, and the checker and clause loader are fakes passed in as
keyword arguments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from notebooklm._app.fact_checks import ChildClaim
from notebooklm.db.models import FactCheck
from notebooklm.tui.jobs.handlers.fact_check import run_fact_check
from notebooklm.tui.jobs.runner import JobCancelled, JobContext
from notebooklm.tui.jobs.store import ItemStatus, Job, JobStatus

HEDGED_TOKENS = [{"text": "It", "lemma": "it"}, {"text": "might", "lemma": "might"}]
PLAIN_TOKENS = [{"text": "Water", "lemma": "water"}, {"text": "boils", "lemma": "boil"}]
TAGGED = {"mood": "declarative", "modality": "high"}


def _child(
    external_id: str,
    *,
    sfl: dict[str, Any] | None = TAGGED,
    tokens: list[dict[str, Any]] | None = PLAIN_TOKENS,
) -> ChildClaim:
    return ChildClaim(
        external_id=external_id,
        text=f"claim {external_id}",
        parent_text="parent text",
        notebook_id="nb-1",
        parent_id=7,
        sfl=sfl,
        tokens=tokens,
    )


class FakeStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.fields: dict[str, Any] = {}
        self.cancel = False

    def add_item(self, job_id: str, name: str, kind: str = "") -> str:
        item_id = f"item-{len(self.items) + 1}"
        self.items[item_id] = {"name": name, "kind": kind, "status": None, "error": ""}
        return item_id

    def update_item(self, job_id: str, item_id: str, **fields: Any) -> None:
        self.items[item_id].update(fields)

    def update(self, job_id: str, **fields: Any) -> None:
        self.fields.update(fields)

    def is_cancel_requested(self, job_id: str) -> bool:
        return self.cancel


class FakeSession:
    """Async context manager that records ORM adds, executed statements and commits."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.statements: list[Any] = []
        self.commits = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, stmt: Any) -> None:
        self.statements.append(stmt)

    async def commit(self) -> None:
        self.commits += 1

    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def fact_rows(self) -> list[FactCheck]:
        return [obj for obj in self.added if isinstance(obj, FactCheck)]

    def passed_values(self) -> list[bool]:
        """``fact_check_passed`` values set by executed UPDATE statements."""
        values = []
        for stmt in self.statements:
            params = stmt.compile().params
            if "fact_check_passed" in params:
                values.append(params["fact_check_passed"])
        return values


@dataclass
class FakeResult:
    verdict: str
    confidence: float | None = 0.9
    probabilities: dict[str, float] | None = None
    sift_steps: dict[str, Any] | None = None
    citations: list[dict[str, Any]] | None = None
    model: str | None = "fake-model"


class FakeChecker:
    framework_available = True

    def __init__(self, verdict: str = "supported", error: Exception | None = None) -> None:
        self.verdict = verdict
        self.error = error
        self.calls: list[str] = []

    async def check(self, claim: str, parent_context: str, sfl: dict[str, Any] | None) -> Any:
        self.calls.append(claim)
        if self.error is not None:
            raise self.error
        return FakeResult(verdict=self.verdict)


def _loader(children: list[ChildClaim], seen: dict[str, Any] | None = None):
    async def load(session: Any, notebook_id: str | None = None, parent_id: int | None = None):
        if seen is not None:
            seen.update(notebook_id=notebook_id, parent_id=parent_id)
        return children

    return load


def _ctx(store: FakeStore, *, trace_id: str | None = "trace-abc", payload=None) -> JobContext:
    job = Job(
        id="job-1",
        kind="fact_check",
        status=JobStatus.RUNNING,
        notebook_id="nb-1",
        payload=payload or {},
    )
    return JobContext(job, store, trace_id=trace_id)  # type: ignore[arg-type]


async def test_untagged_child_fails_before_any_checker_call() -> None:
    session = FakeSession()
    checker = FakeChecker()
    children = [_child("c1"), _child("c2", sfl=None, tokens=None)]

    with pytest.raises(RuntimeError, match=r"run sfl_tag first \(1 children untagged\)"):
        await run_fact_check(
            _ctx(FakeStore()),
            session_factory=lambda: session,
            checker_factory=lambda: checker,
            loader=_loader(children),
        )

    assert checker.calls == []
    assert session.added == []
    assert session.commits == 0


async def test_hedged_child_recorded_not_checkworthy_without_checker_call() -> None:
    session = FakeSession()
    checker = FakeChecker()
    store = FakeStore()

    summary = await run_fact_check(
        _ctx(store),
        session_factory=lambda: session,
        checker_factory=lambda: checker,
        loader=_loader([_child("c1", tokens=HEDGED_TOKENS)]),
    )

    assert checker.calls == []
    [row] = session.fact_rows()
    assert row.verdict == "not_checkworthy"
    assert row.clause_external_id == "c1"
    assert row.job_id == "job-1"
    assert session.passed_values() == []
    assert store.items["item-1"]["status"] == ItemStatus.SKIPPED
    assert store.items["item-1"]["error"] == "hedge cue: might"
    assert "not_checkworthy 1" in summary


async def test_checkworthy_child_recorded_with_trace_and_job_id() -> None:
    session = FakeSession()
    checker = FakeChecker(verdict="supported")

    summary = await run_fact_check(
        _ctx(FakeStore(), trace_id="trace-abc"),
        session_factory=lambda: session,
        checker_factory=lambda: checker,
        loader=_loader([_child("c1")]),
    )

    assert checker.calls == ["claim c1"]
    [row] = session.fact_rows()
    assert row.verdict == "supported"
    assert row.job_id == "job-1"
    assert row.trace_id == "trace-abc"
    assert row.model == "fake-model"
    assert row.confidence == 0.9
    assert isinstance(row.latency_ms, int) and row.latency_ms >= 0
    assert session.passed_values() == [True]
    assert "supported 1" in summary


async def test_contradicted_sets_passed_false() -> None:
    session = FakeSession()

    await run_fact_check(
        _ctx(FakeStore()),
        session_factory=lambda: session,
        checker_factory=lambda: FakeChecker(verdict="contradicted"),
        loader=_loader([_child("c1")]),
    )

    assert session.passed_values() == [False]


async def test_skipped_no_framework_leaves_fact_check_passed_untouched() -> None:
    session = FakeSession()

    summary = await run_fact_check(
        _ctx(FakeStore()),
        session_factory=lambda: session,
        checker_factory=lambda: FakeChecker(verdict="skipped_no_framework"),
        loader=_loader([_child("c1")]),
    )

    [row] = session.fact_rows()
    assert row.verdict == "skipped_no_framework"
    assert session.passed_values() == []
    assert "skipped_no_framework 1" in summary


async def test_two_runs_append_two_rows() -> None:
    session = FakeSession()
    children = [_child("c1")]
    for _ in range(2):
        await run_fact_check(
            _ctx(FakeStore()),
            session_factory=lambda: session,
            checker_factory=lambda: FakeChecker(verdict="unverifiable"),
            loader=_loader(children),
        )

    rows = session.fact_rows()
    assert len(rows) == 2
    assert {row.verdict for row in rows} == {"unverifiable"}
    assert session.passed_values() == []


async def test_scope_is_passed_to_loader() -> None:
    seen: dict[str, Any] = {}

    await run_fact_check(
        _ctx(FakeStore(), payload={"parent_id": 7}),
        session_factory=FakeSession,
        checker_factory=FakeChecker,
        loader=_loader([], seen),
    )

    assert seen == {"notebook_id": "nb-1", "parent_id": 7}


async def test_missing_scope_raises() -> None:
    job = Job(id="job-2", kind="fact_check", status=JobStatus.RUNNING, notebook_id=None)
    ctx = JobContext(job, FakeStore())  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="scope"):
        await run_fact_check(
            ctx,
            session_factory=FakeSession,
            checker_factory=FakeChecker,
            loader=_loader([]),
        )


async def test_cancel_stops_before_next_child() -> None:
    session = FakeSession()
    checker = FakeChecker()
    store = FakeStore()
    store.cancel = True

    with pytest.raises(JobCancelled):
        await run_fact_check(
            _ctx(store),
            session_factory=lambda: session,
            checker_factory=lambda: checker,
            loader=_loader([_child("c1")]),
        )

    assert checker.calls == []
    assert session.added == []


async def test_checker_error_marks_item_failed_and_propagates() -> None:
    session = FakeSession()
    store = FakeStore()
    checker = FakeChecker(error=RuntimeError("exa down"))

    with pytest.raises(RuntimeError, match="exa down"):
        await run_fact_check(
            _ctx(store),
            session_factory=lambda: session,
            checker_factory=lambda: checker,
            loader=_loader([_child("c1")]),
        )

    assert store.items["item-1"]["error"] == "RuntimeError: exa down"
    assert session.fact_rows() == []
