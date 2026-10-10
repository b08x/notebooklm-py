"""Transport-neutral fact-check run controller with an optional human gate.

One :class:`FactCheckRun` walks a queue of child clauses. For each it asks a
**gate** whether the chunk is worth checking:

* ``gate_source="rule"`` — the deterministic :func:`checkworthiness.assess`;
* ``gate_source="jev"`` — the Jev decision model choosing ``checkworthy`` /
  ``meta_dialogue_or_satire`` / ``filler``. A :class:`JevError` falls back to
  the rule gate for that item and emits a ``gate_fallback`` event.

When the gate flags a chunk:

* ``gate_mode="auto"`` records it ``not_checkworthy`` and moves on (the TUI
  ``fact_check`` job);
* ``gate_mode="interactive"`` pauses on a :class:`HumanGate` until someone
  decides Skip (``Y``) or Fact-check (``N``), unless auto-skip (``S``) is on.

Every state change is an event with a monotonically increasing ``seq`` kept in
a ring buffer, so a browser reconnecting with ``after=<seq>`` replays what it
missed (SSE), and the run keeps going with no subscriber at all.

:class:`HumanGate` is also the audio-assessment HITL gate: its
:meth:`HumanGate.sync_gate` blocks a worker thread (``hitl_callback``) on the
owning loop, replacing the TUI's old spin-wait. All decide/toggle methods are
thread-safe.

This module never calls ``dspy.configure()``.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .._preprocessing.checkworthiness import assess
from .._preprocessing.jev import ChoiceQuestion, JevClient, JevError
from ..db.models import Clause
from .fact_checks import (
    ChildClaim,
    VerdictResult,
    record_fact_check,
    record_not_checkworthy,
)
from .sfl_format import format_sfl
from .tracing import trace_url

GATE_SOURCES = ("rule", "jev")
GATE_MODES = ("interactive", "auto")

#: Item statuses shown in the run queue.
ITEM_STATUSES = (
    "pending",
    "active",
    "waiting",
    "verified",
    "refuted",
    "unverifiable",
    "skipped",
    "no_framework",
    "error",
)
VERDICT_STATUS = {
    "supported": "verified",
    "contradicted": "refuted",
    "unverifiable": "unverifiable",
    "skipped_no_framework": "no_framework",
    "not_checkworthy": "skipped",
}

#: Events kept for replay.
EVENT_BUFFER = 5000

#: Jev check-worthiness question; criteria follow the TUI satire classifier
#: ("verifiable factual claims ... or purely subjective, satirical
#: meta-dialogue, or conversational filler").
JEV_GATE_QUESTION = ChoiceQuestion(
    instructions=(
        "Decide whether this chunk of text contains a verifiable factual claim about the "
        "real world or its source material. Use the chunk, its SFL analysis and the "
        "neighbouring lines in the state."
    ),
    criteria={
        "checkworthy": "states at least one specific, verifiable factual claim",
        "meta_dialogue_or_satire": (
            "subjective, satirical, ironic or meta-dialogue about the conversation itself; "
            "nothing empirical to verify"
        ),
        "filler": "conversational filler, greetings, back-channel or fragments with no claim",
    },
)
JEV_CHECKWORTHY = "checkworthy"


class FactChecker(Protocol):
    @property
    def framework_available(self) -> bool: ...

    async def check(
        self, claim: str, parent_context: str, sfl: dict[str, Any] | None
    ) -> VerdictResult: ...


class SflMissingError(RuntimeError):
    """Children in scope have no SFL output; run ``sfl_tag`` first."""


# ---------------------------------------------------------------------------
# Human gate
# ---------------------------------------------------------------------------


class HumanGate:
    """Pause-until-decided gate, safe to drive from any thread.

    :meth:`wait` returns ``True`` to fact-check and ``False`` to skip.
    """

    def __init__(self, on_change: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pending: dict[str, asyncio.Future[bool]] = {}
        self._prompts: dict[str, dict[str, Any]] = {}
        self._auto_skip = False
        self._on_change = on_change

    @property
    def auto_skip(self) -> bool:
        return self._auto_skip

    @property
    def waiting(self) -> dict[str, dict[str, Any]]:
        """Open prompts by item id."""
        return dict(self._prompts)

    def bind(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self._loop = loop or asyncio.get_running_loop()

    async def wait(self, item_id: str, prompt: dict[str, Any] | None = None) -> bool:
        if self._loop is None:
            self.bind()
        if self._auto_skip:
            return False
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._pending[item_id] = future
        self._prompts[item_id] = dict(prompt or {})
        try:
            return await future
        finally:
            self._pending.pop(item_id, None)
            self._prompts.pop(item_id, None)

    def _call(self, fn: Callable[[], None]) -> None:
        loop = self._loop
        if loop is None:
            fn()
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            fn()
        else:
            loop.call_soon_threadsafe(fn)

    def decide(self, item_id: str, check: bool) -> bool:
        """Resolve ``item_id``'s prompt: ``check=True`` fact-checks, ``False`` skips.

        Returns whether a prompt was open for that item.
        """
        if item_id not in self._pending:
            return False

        def resolve() -> None:
            fut = self._pending.get(item_id)
            if fut is not None and not fut.done():
                fut.set_result(check)

        self._call(resolve)
        return True

    def set_auto_skip(self, on: bool) -> None:
        """Toggle auto-skip; turning it on skips every open prompt."""
        self._auto_skip = on

        def resolve_all() -> None:
            if on:
                for fut in list(self._pending.values()):
                    if not fut.done():
                        fut.set_result(False)
            if self._on_change is not None:
                self._on_change({"type": "auto_skip", "auto_skip": on})

        self._call(resolve_all)

    def cancel_all(self) -> None:
        def cancel() -> None:
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.cancel()

        self._call(cancel)

    def sync_gate(self, item_id: str, prompt: dict[str, Any] | None = None) -> bool:
        """Block the calling worker thread until :meth:`wait` resolves on the gate's loop."""
        if self._loop is None:
            raise RuntimeError("HumanGate.bind() must run on the owning loop first")
        future = asyncio.run_coroutine_threadsafe(self.wait(item_id, prompt), self._loop)
        return future.result()


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    flagged: bool
    reason: str
    source: str
    label: str | None = None
    probability: float | None = None
    probabilities: dict[str, float] | None = None


def rule_gate(child: ChildClaim) -> GateResult:
    checkworthy, reason = assess(child.sfl, child.tokens)
    return GateResult(flagged=not checkworthy, reason=reason, source="rule")


async def jev_gate(
    jev: JevClient, child: ChildClaim, context: dict[str, list[dict[str, Any]]] | None
) -> GateResult:
    state = {
        "chunk": child.text,
        "sfl": format_sfl(child.sfl) if child.sfl else None,
        "lines_before": [c["text"] for c in (context or {}).get("before", [])],
        "lines_after": [c["text"] for c in (context or {}).get("after", [])],
    }
    decision = (await jev.decide(state, {"gate": JEV_GATE_QUESTION}))["gate"]
    label = decision.choice
    probability = decision.probabilities.get(label, decision.confidence)
    flagged = label != JEV_CHECKWORTHY
    return GateResult(
        flagged=flagged,
        reason=f"jev: {label}",
        source="jev",
        label=label,
        probability=probability,
        probabilities=decision.probabilities,
    )


# ---------------------------------------------------------------------------
# Context lines
# ---------------------------------------------------------------------------


async def load_contexts(
    session: AsyncSession, children: Sequence[ChildClaim], window: int = 2
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """``{external_id: {"before": [...], "after": [...]}}`` by ``sentence_index``."""
    ids = [c.external_id for c in children]
    if not ids:
        return {}
    me = (
        await session.execute(
            select(Clause.external_id, Clause.run_id, Clause.sentence_index).where(
                Clause.external_id.in_(ids)
            )
        )
    ).all()
    run_ids = {r for _, r, _ in me if r is not None}
    lines: dict[tuple[int, int], dict[str, Any]] = {}
    if run_ids:
        for eid, run_id, idx, text in (
            await session.execute(
                select(Clause.external_id, Clause.run_id, Clause.sentence_index, Clause.text).where(
                    Clause.run_id.in_(run_ids)
                )
            )
        ).all():
            if idx is not None:
                lines[(run_id, idx)] = {"external_id": eid, "sentence_index": idx, "text": text}
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for eid, run_id, idx in me:
        if run_id is None or idx is None:
            out[eid] = {"before": [], "after": []}
            continue
        out[eid] = {
            "before": [
                lines[(run_id, i)] for i in range(idx - window, idx) if (run_id, i) in lines
            ],
            "after": [
                lines[(run_id, i)] for i in range(idx + 1, idx + window + 1) if (run_id, i) in lines
            ],
        }
    return out


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


SessionFactory = Callable[[], AbstractAsyncContextManager[Any]]


@dataclass
class RunItem:
    index: int
    external_id: str
    text: str
    parent_text: str | None
    sfl: dict[str, Any] | None
    status: str = "pending"
    reason: str | None = None
    verdict: str | None = None
    confidence: float | None = None
    probability: float | None = None
    gate: dict[str, Any] | None = None
    sift: dict[str, str] = field(default_factory=dict)
    sift_steps: dict[str, Any] | None = None
    citations: list[dict[str, Any]] | None = None
    rationale: str | None = None
    trace_url: str | None = None
    context: dict[str, list[dict[str, Any]]] = field(
        default_factory=lambda: {"before": [], "after": []}
    )

    @property
    def item_id(self) -> str:
        return f"{self.index:04d}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "index": self.index,
            "external_id": self.external_id,
            "text": self.text,
            "status": self.status,
            "reason": self.reason,
            "verdict": self.verdict,
            "confidence": self.confidence,
            "probability": self.probability,
            "gate": self.gate,
            "sift": self.sift,
            "sift_steps": self.sift_steps,
            "citations": self.citations,
            "rationale": self.rationale,
            "trace_url": self.trace_url,
            "context": self.context,
            "sfl": format_sfl(self.sfl) if self.sfl else None,
        }


def _rationale(result: VerdictResult) -> str:
    steps = result.sift_steps or {}
    coverage = steps.get("find_coverage") if isinstance(steps, dict) else None
    if isinstance(coverage, dict) and coverage.get("coverage_summary"):
        return str(coverage["coverage_summary"])
    if result.verdict == "skipped_no_framework":
        return "SIFT framework not installed; nothing was checked."
    return f"Verdict: {result.verdict}"


def _accepts_on_step(checker: Any) -> bool:
    try:
        return "on_step" in inspect.signature(checker.check).parameters
    except (TypeError, ValueError):
        return False


class FactCheckRun:
    """One fact-check run over a queue of child clauses."""

    def __init__(
        self,
        children: Sequence[ChildClaim],
        *,
        checker: FactChecker,
        session_factory: SessionFactory,
        gate_source: str = "rule",
        gate_mode: str = "interactive",
        jev: JevClient | None = None,
        contexts: dict[str, dict[str, list[dict[str, Any]]]] | None = None,
        run_id: str | None = None,
        job_id: str | None = None,
        trace_id: str | None = None,
        label: str = "",
        auto_skip: bool = False,
        stop_on_error: bool = False,
        before_item: Callable[[], None] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if gate_source not in GATE_SOURCES:
            raise ValueError(f"gate_source must be one of {GATE_SOURCES}")
        if gate_mode not in GATE_MODES:
            raise ValueError(f"gate_mode must be one of {GATE_MODES}")
        self.id = run_id or uuid.uuid4().hex[:8]
        self.job_id = job_id or f"web:{self.id}"
        self.trace_id = trace_id
        self.label = label
        self.gate_source = gate_source
        self.gate_mode = gate_mode
        self.checker = checker
        self.session_factory = session_factory
        self.jev = jev
        self.stop_on_error = stop_on_error
        self.before_item = before_item
        self.on_event = on_event
        self.items = [
            RunItem(
                index=i,
                external_id=c.external_id,
                text=c.text,
                parent_text=c.parent_text,
                sfl=c.sfl,
                context=(contexts or {}).get(c.external_id, {"before": [], "after": []}),
            )
            for i, c in enumerate(children, start=1)
        ]
        self._children = list(children)
        self.status = "created"
        self.error: str | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.counts: Counter[str] = Counter()
        self.gate = HumanGate(on_change=self._emit_raw)
        if auto_skip:
            self.gate.set_auto_skip(True)
        self._events: deque[dict[str, Any]] = deque(maxlen=EVENT_BUFFER)
        self._seq = 0
        self._changed = asyncio.Event()
        self._resume = asyncio.Event()
        self._resume.set()
        self._task: asyncio.Task[None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # -- events ------------------------------------------------------------

    @property
    def last_seq(self) -> int:
        return self._seq

    @property
    def finished(self) -> bool:
        return self.status in ("finished", "cancelled", "failed")

    def _emit_raw(self, event: dict[str, Any]) -> None:
        self._seq += 1
        event = {"seq": self._seq, "run_id": self.id, "ts": time.time(), **event}
        self._events.append(event)
        changed, self._changed = self._changed, asyncio.Event()
        changed.set()
        if self.on_event is not None:
            self.on_event(event)

    def _emit(self, type_: str, **data: Any) -> None:
        self._emit_raw({"type": type_, **data})

    def _emit_threadsafe(self, type_: str, **data: Any) -> None:
        """Emit from any thread; a worker thread waits until the loop has recorded it.

        Waiting keeps worker events strictly ordered before whatever the loop
        emits after the worker returns.
        """
        loop = self._loop
        try:
            on_loop = asyncio.get_running_loop() is loop
        except RuntimeError:
            on_loop = False
        if loop is None or on_loop or loop.is_closed():
            self._emit(type_, **data)
            return
        done = threading.Event()

        def emit() -> None:
            try:
                self._emit(type_, **data)
            finally:
                done.set()

        loop.call_soon_threadsafe(emit)
        done.wait(timeout=5.0)

    def events_after(self, after_seq: int) -> list[dict[str, Any]]:
        return [e for e in self._events if e["seq"] > after_seq]

    async def subscribe(self, after_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        """Replay events after ``after_seq``, then stream new ones until the run ends."""
        cursor = after_seq
        while True:
            changed = self._changed
            pending = self.events_after(cursor)
            for event in pending:
                cursor = event["seq"]
                yield event
            if pending:
                continue
            if self.finished:
                return
            await changed.wait()

    # -- control -----------------------------------------------------------

    def start(self) -> asyncio.Task[None]:
        """Run in the background on the current loop."""
        self._task = asyncio.get_running_loop().create_task(self.run())
        return self._task

    def decide(self, item_id: str, check: bool) -> bool:
        return self.gate.decide(item_id, check)

    def set_auto_skip(self, on: bool) -> None:
        self.gate.set_auto_skip(on)

    def pause(self) -> None:
        if not self.finished and self._resume.is_set():
            self._resume.clear()
            self.status = "paused"
            self._emit("run_paused")

    def resume(self) -> None:
        if not self.finished and not self._resume.is_set():
            self._resume.set()
            self.status = "running"
            self._emit("run_resumed")

    def cancel(self) -> None:
        if self.finished:
            return
        self.gate.cancel_all()
        if self._task is not None:
            self._task.cancel()
        if self.started_at is None:
            # Never entered run(): nothing will emit run_finished, so finish here.
            self.status = "cancelled"
            self.finished_at = time.time()
            self._emit("run_finished", status=self.status, counts={})

    def snapshot(self) -> dict[str, Any]:
        now = self.finished_at or time.time()
        waiting = self.gate.waiting
        return {
            "id": self.id,
            "job_id": self.job_id,
            "label": self.label,
            "status": self.status,
            "error": self.error,
            "gate_source": self.gate_source,
            "gate_mode": self.gate_mode,
            "auto_skip": self.gate.auto_skip,
            "total": len(self.items),
            "done": sum(1 for i in self.items if i.status not in ("pending", "active", "waiting")),
            "counts": {s: sum(1 for i in self.items if i.status == s) for s in ITEM_STATUSES},
            "elapsed_s": round(now - self.started_at, 1) if self.started_at else 0.0,
            "last_seq": self._seq,
            "waiting": [{"item_id": k, **v} for k, v in waiting.items()],
            "items": [i.to_dict() for i in self.items],
        }

    # -- loop --------------------------------------------------------------

    async def _gate_for(self, item: RunItem, child: ChildClaim) -> GateResult:
        if self.gate_source == "jev":
            try:
                return await jev_gate(self.jev or JevClient(), child, item.context)
            except JevError as e:
                self._emit("gate_fallback", item_id=item.item_id, error=str(e))
        return rule_gate(child)

    async def _record_skip(self, item: RunItem, reason: str) -> None:
        async with self.session_factory() as session:
            await record_not_checkworthy(
                session, item.external_id, job_id=self.job_id, trace_id=self.trace_id
            )
        item.status = "skipped"
        item.verdict = "not_checkworthy"
        item.reason = reason
        item.rationale = reason
        self.counts["not_checkworthy"] += 1
        self._emit("item_done", item=item.to_dict())

    async def _check(self, item: RunItem, child: ChildClaim) -> None:
        def on_step(step: str, status: str) -> None:
            item.sift[step] = status
            self._emit_threadsafe("sift_step", item_id=item.item_id, step=step, status=status)

        started = time.perf_counter()
        if _accepts_on_step(self.checker):
            result = await self.checker.check(  # type: ignore[call-arg]
                child.text, child.parent_text or "", child.sfl, on_step=on_step
            )
        else:
            result = await self.checker.check(child.text, child.parent_text or "", child.sfl)
        latency_ms = round((time.perf_counter() - started) * 1000)
        async with self.session_factory() as session:
            await record_fact_check(
                session,
                item.external_id,
                result,
                job_id=self.job_id,
                trace_id=self.trace_id,
                latency_ms=latency_ms,
            )
        item.verdict = result.verdict
        item.status = VERDICT_STATUS.get(result.verdict, "unverifiable")
        item.confidence = result.confidence
        item.sift_steps = result.sift_steps
        item.citations = result.citations
        item.rationale = _rationale(result)
        item.trace_url = trace_url(self.trace_id)
        self.counts[result.verdict] += 1
        self._emit("item_done", item=item.to_dict())

    async def _process(self, item: RunItem, child: ChildClaim) -> None:
        item.status = "active"
        self._emit("item_started", item_id=item.item_id, external_id=item.external_id)
        gate = await self._gate_for(item, child)
        item.probability = gate.probability
        item.gate = {
            "flagged": gate.flagged,
            "reason": gate.reason,
            "source": gate.source,
            "label": gate.label,
            "probability": gate.probability,
            "probabilities": gate.probabilities,
        }
        if gate.flagged:
            check = False
            if self.gate_mode == "interactive" and not self.gate.auto_skip:
                item.status = "waiting"
                self._emit("gate", item_id=item.item_id, gate=item.gate, text=item.text)
                check = await self.gate.wait(item.item_id, {**item.gate, "text": item.text})
                item.status = "active"
                self._emit(
                    "gate_resolved",
                    item_id=item.item_id,
                    decision="fact_check" if check else "skip",
                )
            if not check:
                await self._record_skip(item, gate.reason)
                return
        await self._check(item, child)

    async def run(self) -> None:
        """Process every item in order. Use :meth:`start` to run it in the background."""
        self._loop = asyncio.get_running_loop()
        self.gate.bind(self._loop)
        self.status = "running"
        self.started_at = time.time()
        self._emit("run_started", total=len(self.items), label=self.label)
        try:
            for item, child in zip(self.items, self._children, strict=True):
                await self._resume.wait()
                if self.before_item is not None:
                    self.before_item()
                try:
                    await self._process(item, child)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    item.status = "error"
                    item.reason = f"{type(e).__name__}: {e}"
                    self._emit("item_error", item_id=item.item_id, error=item.reason)
                    if self.stop_on_error:
                        raise
            self.status = "finished"
        except asyncio.CancelledError:
            self.status = "cancelled"
            raise
        except Exception as e:
            self.status = "failed"
            self.error = f"{type(e).__name__}: {e}"
            raise
        finally:
            self.finished_at = time.time()
            self._emit("run_finished", status=self.status, counts=dict(self.counts))

    def summary(self) -> str:
        parts = ", ".join(
            f"{verdict} {self.counts[verdict]}"
            for verdict in (
                "supported",
                "contradicted",
                "unverifiable",
                "skipped_no_framework",
                "not_checkworthy",
            )
        )
        return f"fact-checked {len(self.items)} children: {parts}"


def require_sfl(children: Sequence[ChildClaim]) -> None:
    untagged = sum(1 for child in children if child.sfl is None)
    if untagged:
        raise SflMissingError(f"run sfl_tag first ({untagged} children untagged)")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class RunRegistry:
    """Keeps runs alive independently of any SSE connection (server app state)."""

    def __init__(self, keep: int = 50) -> None:
        self._runs: dict[str, FactCheckRun] = {}
        self._keep = keep

    def add(self, run: FactCheckRun) -> FactCheckRun:
        self._runs[run.id] = run
        finished = [r for r in self._runs.values() if r.finished]
        for old in finished[: max(0, len(self._runs) - self._keep)]:
            self._runs.pop(old.id, None)
        return run

    def get(self, run_id: str) -> FactCheckRun | None:
        return self._runs.get(run_id)

    def all(self) -> list[FactCheckRun]:
        return list(self._runs.values())

    def active(self) -> list[FactCheckRun]:
        return [r for r in self._runs.values() if not r.finished]

    async def shutdown(self) -> None:
        tasks = []
        for run in self.active():
            run.cancel()
            if run._task is not None:
                tasks.append(run._task)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# ---------------------------------------------------------------------------
# Gate comparison (scripts/compare_gates.py)
# ---------------------------------------------------------------------------


def compare_gates(pairs: Sequence[tuple[bool, bool]]) -> dict[str, Any]:
    """Agreement between ``(rule_flagged, jev_flagged)`` pairs.

    Returns the agreement rate, Cohen's kappa and a 2x2 confusion matrix keyed
    ``"rule=<check|skip>/jev=<check|skip>"``.
    """
    labels = {False: "check", True: "skip"}
    matrix = {f"rule={labels[r]}/jev={labels[j]}": 0 for r in (False, True) for j in (False, True)}
    for rule_flagged, jev_flagged in pairs:
        matrix[f"rule={labels[rule_flagged]}/jev={labels[jev_flagged]}"] += 1
    n = len(pairs)
    agree = sum(1 for r, j in pairs if r == j)
    p_o = agree / n if n else 0.0
    p_rule = sum(1 for r, _ in pairs if r) / n if n else 0.0
    p_jev = sum(1 for _, j in pairs if j) / n if n else 0.0
    p_e = p_rule * p_jev + (1 - p_rule) * (1 - p_jev)
    kappa = (p_o - p_e) / (1 - p_e) if n and p_e < 1 else (1.0 if n else 0.0)
    return {"n": n, "agreement": p_o, "kappa": kappa, "confusion": matrix}


async def sample_children(session: AsyncSession, n: int, seed: float = 0.42) -> list[ChildClaim]:
    """``n`` random SFL-tagged active-run children (repeatable for a given ``seed``)."""
    from sqlalchemy import func

    from ..db.models import ChunkRun, ParentChunk

    await session.execute(select(func.setseed(seed)))
    stmt = (
        select(Clause, ParentChunk.text, ChunkRun.notebook_id)
        .join(ChunkRun, Clause.run_id == ChunkRun.id)
        .outerjoin(ParentChunk, Clause.parent_id == ParentChunk.id)
        .where(ChunkRun.is_active.is_(True), Clause.sfl.is_not(None))
        .order_by(func.random())
        .limit(n)
    )
    return [
        ChildClaim(
            external_id=c.external_id,
            text=c.text,
            parent_text=parent_text,
            notebook_id=nb,
            parent_id=c.parent_id,
            sfl=c.sfl,
            tokens=c.tokens if isinstance(c.tokens, list) else None,
        )
        for c, parent_text, nb in (await session.execute(stmt)).all()
    ]


async def run_gate_comparison(
    session: AsyncSession, n: int, jev: JevClient | None = None
) -> dict[str, Any]:
    """Run both gates over a sample of stored chunks and compare them."""
    children = await sample_children(session, n)
    contexts = await load_contexts(session, children)
    client = jev or JevClient()
    pairs: list[tuple[bool, bool]] = []
    errors = 0
    for child in children:
        rule = rule_gate(child)
        try:
            jev_result = await jev_gate(client, child, contexts.get(child.external_id))
        except JevError:
            errors += 1
            continue
        pairs.append((rule.flagged, jev_result.flagged))
    return {**compare_gates(pairs), "sampled": len(children), "jev_errors": errors}
