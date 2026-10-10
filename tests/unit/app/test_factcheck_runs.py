"""Fact-check run controller: gate, auto-skip, replay, Jev gate (facts 34-40, 58)."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import factcheck_runs as fr
from notebooklm._app.fact_checks import ChildClaim
from notebooklm._preprocessing.jev import Decision, JevError
from notebooklm.db.models import Clause
from tests._fixtures.corpus_seed import Seeder
from tests._fixtures.postgres import pg_session  # noqa: F401

TAGGED = {"mood": "declarative", "modality": "high"}
PLAIN = [{"text": "Water", "lemma": "water"}, {"text": "boils", "lemma": "boil"}]
HEDGED = [{"text": "It", "lemma": "it"}, {"text": "might", "lemma": "might"}]


def _child(eid: str, tokens: list[dict[str, Any]] = PLAIN, sfl: Any = TAGGED) -> ChildClaim:
    return ChildClaim(eid, f"claim {eid}", "parent", "nb", 1, sfl, tokens)


class Recorder:
    """Session stand-in: records ORM adds/commits; ``record_*`` only add + commit."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def execute(self, stmt: Any) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def __aenter__(self) -> Recorder:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def verdicts(self) -> list[tuple[str, str]]:
        return [(o.clause_external_id, o.verdict) for o in self.added]


@dataclass
class Result:
    verdict: str
    confidence: float | None = 0.8
    probabilities: dict[str, float] | None = None
    sift_steps: dict[str, Any] | None = None
    citations: list[dict[str, Any]] | None = None
    model: str | None = "m"


class Checker:
    framework_available = True

    def __init__(self, verdict: str = "supported", fail_on: str | None = None) -> None:
        self.verdict = verdict
        self.fail_on = fail_on
        self.calls: list[str] = []

    async def check(self, claim: str, parent_context: str, sfl: Any, on_step: Any = None) -> Result:
        self.calls.append(claim)
        if self.fail_on and self.fail_on in claim:
            raise RuntimeError("boom")
        if on_step is not None:
            await asyncio.to_thread(on_step, "stop", "running")
            await asyncio.to_thread(on_step, "stop", "done")
        return Result(
            self.verdict, sift_steps={"find_coverage": {"coverage_summary": "sources agree"}}
        )


def _run(children: list[ChildClaim], **kw: Any) -> tuple[fr.FactCheckRun, Recorder, Checker]:
    rec = Recorder()
    checker = kw.pop("checker", Checker())
    run = fr.FactCheckRun(children, checker=checker, session_factory=lambda: rec, **kw)
    return run, rec, checker


async def _wait_for(predicate: Any, timeout: float = 2.0) -> None:
    async def loop() -> None:
        while not predicate():
            await asyncio.sleep(0.005)

    await asyncio.wait_for(loop(), timeout)


@pytest.mark.asyncio
async def test_gate_pauses_until_decide() -> None:
    run, rec, checker = _run([_child("c1", HEDGED), _child("c2")])
    task = run.start()
    await _wait_for(lambda: run.gate.waiting)
    snap = run.snapshot()
    assert snap["items"][0]["status"] == "waiting" and snap["waiting"][0]["item_id"] == "0001"
    assert checker.calls == []  # paused: nothing checked yet
    assert run.decide("0001", check=True) is True  # N = fact-check anyway
    await task
    assert checker.calls == ["claim c1", "claim c2"]
    assert rec.verdicts() == [("c1", "supported"), ("c2", "supported")]
    types = [e["type"] for e in run.events_after(0)]
    assert types.index("gate") < types.index("gate_resolved")
    assert run.snapshot()["counts"]["verified"] == 2
    assert run.decide("0001", True) is False  # nothing open any more


@pytest.mark.asyncio
async def test_skip_decision_records_not_checkworthy() -> None:
    run, rec, checker = _run([_child("c1", HEDGED)])
    task = run.start()
    await _wait_for(lambda: run.gate.waiting)
    run.decide("0001", check=False)
    await task
    assert checker.calls == [] and rec.verdicts() == [("c1", "not_checkworthy")]
    item = run.snapshot()["items"][0]
    assert item["status"] == "skipped" and item["rationale"] == "hedge cue: might"


@pytest.mark.asyncio
async def test_auto_skip_resolves_open_gate_and_later_ones() -> None:
    run, rec, _ = _run([_child("c1", HEDGED), _child("c2", HEDGED), _child("c3")])
    task = run.start()
    await _wait_for(lambda: run.gate.waiting)
    run.set_auto_skip(True)
    await task
    assert rec.verdicts() == [
        ("c1", "not_checkworthy"),
        ("c2", "not_checkworthy"),
        ("c3", "supported"),
    ]
    assert [e["type"] for e in run.events_after(0)].count("gate") == 1
    assert any(e["type"] == "auto_skip" and e["auto_skip"] for e in run.events_after(0))


@pytest.mark.asyncio
async def test_auto_mode_never_waits() -> None:
    run, rec, _ = _run([_child("c1", HEDGED)], gate_mode="auto")
    await run.run()
    assert rec.verdicts() == [("c1", "not_checkworthy")]


@pytest.mark.asyncio
async def test_subscribe_replays_missed_events_then_streams() -> None:
    run, _, _ = _run([_child("c1", HEDGED), _child("c2")])
    task = run.start()
    await _wait_for(lambda: run.gate.waiting)
    seen_first = [e async for e in _take(run.subscribe(0), 3)]
    cursor = seen_first[-1]["seq"]
    run.decide("0001", True)
    await task
    rest = [e async for e in run.subscribe(cursor)]
    assert rest[0]["seq"] == cursor + 1
    assert rest[-1]["type"] == "run_finished"
    seqs = [e["seq"] for e in seen_first + rest]
    assert seqs == list(range(1, len(seqs) + 1))
    # A late subscriber gets the whole history and then stops.
    assert [e["seq"] async for e in run.subscribe(0)] == seqs


async def _take(it: Any, n: int) -> Any:
    count = 0
    async for item in it:
        yield item
        count += 1
        if count == n:
            return


@pytest.mark.asyncio
async def test_sift_step_events_from_worker_thread() -> None:
    run, _, _ = _run([_child("c1")])
    await run.run()
    steps = [(e["step"], e["status"]) for e in run.events_after(0) if e["type"] == "sift_step"]
    assert steps == [("stop", "running"), ("stop", "done")]
    item = run.snapshot()["items"][0]
    assert item["sift"] == {"stop": "done"} and item["rationale"] == "sources agree"


@pytest.mark.asyncio
async def test_checker_without_on_step_and_trace_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class Plain:
        framework_available = True

        async def check(self, claim: str, parent: str, sfl: Any) -> Result:
            return Result("skipped_no_framework")

    monkeypatch.setenv("LANGFUSE_HOST", "https://lf.example")
    run, _, _ = _run([_child("c1")], checker=Plain(), trace_id="tr-1")
    await run.run()
    item = run.snapshot()["items"][0]
    assert item["status"] == "no_framework"
    assert item["trace_url"] == "https://lf.example/trace/tr-1"
    assert "not installed" in item["rationale"]


@pytest.mark.asyncio
async def test_item_error_continues_unless_stop_on_error() -> None:
    run, rec, _ = _run([_child("c1"), _child("c2")], checker=Checker(fail_on="c1"))
    await run.run()
    assert [i["status"] for i in run.snapshot()["items"]] == ["error", "verified"]
    run2, _, _ = _run([_child("c1")], checker=Checker(fail_on="c1"), stop_on_error=True)
    with pytest.raises(RuntimeError):
        await run2.run()
    assert run2.status == "failed" and run2.error == "RuntimeError: boom"


@pytest.mark.asyncio
async def test_pause_resume_cancel() -> None:
    run, _, checker = _run([_child("c1", HEDGED), _child("c2")])
    run.pause()  # before start: status stays paused until resumed
    task = run.start()
    await asyncio.sleep(0.02)
    assert checker.calls == [] and not run.gate.waiting
    run.resume()
    await _wait_for(lambda: run.gate.waiting)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert run.status == "cancelled" and run.finished
    run.cancel()  # idempotent
    assert run.events_after(0)[-1]["type"] == "run_finished"


class FakeJev:
    def __init__(self, choice: str = "meta_dialogue_or_satire", error: bool = False) -> None:
        self.choice = choice
        self.error = error
        self.states: list[dict[str, Any]] = []

    async def decide(self, state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Decision]:
        self.states.append(state)
        assert set(questions["gate"].criteria) == {
            "checkworthy",
            "meta_dialogue_or_satire",
            "filler",
        }
        if self.error:
            raise JevError("alpha endpoint down")
        probs = {"checkworthy": 0.2, "meta_dialogue_or_satire": 0.62, "filler": 0.18}
        return {"gate": Decision(self.choice, 0.62, probs)}


@pytest.mark.asyncio
async def test_jev_gate_probability_and_context() -> None:
    jev = FakeJev()
    ctx = {"c1": {"before": [{"text": "prev"}], "after": [{"text": "next"}]}}
    run, _, _ = _run([_child("c1")], gate_source="jev", jev=jev, contexts=ctx)
    task = run.start()
    await _wait_for(lambda: run.gate.waiting)
    gate = run.snapshot()["waiting"][0]
    assert gate["source"] == "jev" and gate["label"] == "meta_dialogue_or_satire"
    assert gate["probability"] == pytest.approx(0.62)
    assert jev.states[0]["lines_before"] == ["prev"] and jev.states[0]["lines_after"] == ["next"]
    run.decide("0001", False)
    await task


@pytest.mark.asyncio
async def test_jev_checkworthy_passes_and_error_falls_back_to_rule() -> None:
    run, rec, _ = _run([_child("c1", HEDGED)], gate_source="jev", jev=FakeJev("checkworthy"))
    await run.run()
    assert rec.verdicts() == [("c1", "supported")]  # Jev overrides the hedge rule

    run, rec, _ = _run(
        [_child("c1", HEDGED)], gate_source="jev", jev=FakeJev(error=True), gate_mode="auto"
    )
    await run.run()
    assert rec.verdicts() == [("c1", "not_checkworthy")]
    assert any(e["type"] == "gate_fallback" for e in run.events_after(0))


def test_bad_options_and_require_sfl() -> None:
    with pytest.raises(ValueError):
        _run([], gate_source="nope")
    with pytest.raises(ValueError):
        _run([], gate_mode="nope")
    with pytest.raises(fr.SflMissingError, match="run sfl_tag first"):
        fr.require_sfl([_child("c1", sfl=None)])


@pytest.mark.asyncio
async def test_human_gate_sync_gate_from_worker_thread() -> None:
    gate = fr.HumanGate()
    gate.bind()
    result: dict[str, bool] = {}

    def worker() -> None:
        result["check"] = gate.sync_gate("audio-1", {"text": "x"})

    thread = threading.Thread(target=worker)
    thread.start()
    await _wait_for(lambda: gate.waiting)
    # decide() from yet another thread (the TUI key handler thread).
    await asyncio.to_thread(gate.decide, "audio-1", False)
    await asyncio.to_thread(thread.join, 2)
    assert result == {"check": False}

    gate.set_auto_skip(True)
    assert await gate.wait("audio-2") is False


def test_human_gate_unbound_sync_gate_raises() -> None:
    with pytest.raises(RuntimeError):
        fr.HumanGate().sync_gate("x")
    gate = fr.HumanGate()
    gate.set_auto_skip(True)  # unbound: applies immediately
    gate.cancel_all()
    assert gate.auto_skip is True and gate.decide("missing", True) is False


@pytest.mark.asyncio
async def test_registry_keeps_runs_and_shutdown_cancels() -> None:
    reg = fr.RunRegistry(keep=1)
    done, _, _ = _run([_child("c1")])
    await done.run()
    reg.add(done)
    live, _, _ = _run([_child("c2", HEDGED)])
    live.start()
    reg.add(live)
    assert reg.get(live.id) is live and reg.active() == [live]
    assert reg.get(done.id) is None  # oldest finished run evicted past ``keep``
    await reg.shutdown()
    assert live.finished and reg.all() == [live]


@pytest.mark.asyncio
async def test_load_contexts_against_postgres(pg_session: AsyncSession) -> None:  # noqa: F811
    s = Seeder(pg_session)
    await s.ingest("t", "l0|l1|l2|l3|l4|l5")
    rows = (
        (
            await pg_session.execute(
                select(Clause.external_id)
                .where(Clause.document_id == s.doc("t"))
                .order_by(Clause.sentence_index)
            )
        )
        .scalars()
        .all()
    )
    children = [ChildClaim(rows[3], "l3", None, None, None, None, None)]
    ctx = await fr.load_contexts(pg_session, children)
    assert [c["text"] for c in ctx[rows[3]]["before"]] == ["l1", "l2"]
    assert [c["text"] for c in ctx[rows[3]]["after"]] == ["l4", "l5"]
    assert await fr.load_contexts(pg_session, []) == {}


def test_compare_gates_agreement_and_kappa() -> None:
    out = fr.compare_gates([(True, True), (False, False), (True, False), (False, False)])
    assert out["n"] == 4 and out["agreement"] == 0.75
    assert out["confusion"] == {
        "rule=check/jev=check": 2,
        "rule=check/jev=skip": 0,
        "rule=skip/jev=check": 1,
        "rule=skip/jev=skip": 1,
    }
    assert out["kappa"] == pytest.approx(0.5)
    assert fr.compare_gates([])["agreement"] == 0.0
    assert fr.compare_gates([(True, True)])["kappa"] == 1.0


@pytest.mark.asyncio
async def test_run_gate_comparison_on_stored_chunks(pg_session: AsyncSession) -> None:  # noqa: F811
    from sqlalchemy import update

    s = Seeder(pg_session)
    await s.ingest("g", "Water boils|It might rain")
    await pg_session.execute(
        update(Clause).where(Clause.document_id == s.doc("g")).values(sfl=TAGGED)
    )

    class AlwaysCheck(FakeJev):
        async def decide(
            self, state: dict[str, Any], questions: dict[str, Any]
        ) -> dict[str, Decision]:
            if "rain" in state["chunk"]:
                raise JevError("x")
            return {"gate": Decision("checkworthy", 0.9, {"checkworthy": 0.9})}

    report = await fr.run_gate_comparison(pg_session, 10_000, jev=AlwaysCheck())  # type: ignore[arg-type]
    assert report["sampled"] >= 2 and report["jev_errors"] >= 1
    assert report["n"] == report["sampled"] - report["jev_errors"]


def test_compare_gates_script_imports() -> None:
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "compare_gates.py"
    spec = importlib.util.spec_from_file_location("compare_gates", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert callable(module.main)
