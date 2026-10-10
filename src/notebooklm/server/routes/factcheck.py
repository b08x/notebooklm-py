"""Fact-check run routes — ``/v1/corpus/factcheck/runs``.

Runs are :class:`~notebooklm._app.factcheck_runs.FactCheckRun` objects kept in
the app's :class:`~notebooklm._app.factcheck_runs.RunRegistry`, so they keep
going when the browser tab closes. Events stream over SSE and replay from
``?after=<seq>``; decisions and the auto-skip toggle drive the run's human gate.

This module imports NO ``click`` / ``rich`` / ``cli``.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..._app.fact_checks import load_children
from ..._app.factcheck_runs import (
    FactCheckRun,
    SflMissingError,
    load_contexts,
    require_sfl,
)
from .._corpus import (
    CorpusServices,
    TypedHTTPError,
    corpus_services,
    scope_from,
    sse_response,
)
from .corpus import SessionDep

__all__ = ["router"]

router = APIRouter(prefix="/corpus/factcheck", tags=["factcheck"])

ServicesDep = Annotated[CorpusServices, Depends(corpus_services)]


def _run(services: CorpusServices, run_id: str) -> FactCheckRun:
    run = services.runs.get(run_id)
    if run is None:
        raise TypedHTTPError(404, "not_found", f"no fact-check run {run_id!r}")
    return run


class StartBody(BaseModel):
    scope: dict[str, Any]
    gate_source: Literal["rule", "jev"] = "rule"
    gate_mode: Literal["interactive", "auto"] = "interactive"
    auto_skip: bool = False
    label: str | None = None


@router.post("/runs", status_code=201)
async def start_run(body: StartBody, session: SessionDep, services: ServicesDep) -> dict[str, Any]:
    """Start a fact-check run over a notebook, documents, runs or a chunk selection.

    ``409 sfl_required`` when chunks in scope have no SFL yet (run ``sfl_tag``
    first via ``POST /corpus/sfl/runs`` with the same scope).
    """
    scope = scope_from(body.scope)
    children = await load_children(session, scope=scope)
    if not children:
        raise TypedHTTPError(404, "no_chunks", f"no chunks in scope ({scope.describe()})")
    try:
        require_sfl(children)
    except SflMissingError as e:
        raise TypedHTTPError(409, "sfl_required", str(e), scope=scope.to_dict()) from e
    contexts = await load_contexts(session, children)
    await session.close()
    run = FactCheckRun(
        children,
        checker=services.checker_factory(),
        session_factory=services.session_maker,
        gate_source=body.gate_source,
        gate_mode=body.gate_mode,
        jev=services.jev_factory() if body.gate_source == "jev" else None,
        contexts=contexts,
        label=body.label or scope.describe(),
        auto_skip=body.auto_skip,
    )
    services.runs.add(run)
    run.start(traced=True)
    return run.snapshot()


@router.get("/runs")
async def list_runs(services: ServicesDep) -> dict[str, Any]:
    return {
        "items": [
            {k: v for k, v in r.snapshot().items() if k != "items"} for r in services.runs.all()
        ]
    }


@router.get("/runs/{run_id}")
async def get_run(run_id: str, services: ServicesDep) -> dict[str, Any]:
    return _run(services, run_id).snapshot()


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str, services: ServicesDep, after: Annotated[int, Query(ge=0)] = 0
) -> Any:
    """SSE of the run's events after ``after`` (replays what a reconnecting tab missed)."""
    return sse_response(_run(services, run_id).subscribe(after))


class DecisionBody(BaseModel):
    item_id: str
    decision: Literal["skip", "fact_check"]


@router.post("/runs/{run_id}/decision")
async def decide(run_id: str, body: DecisionBody, services: ServicesDep) -> dict[str, Any]:
    """Resolve the gate: ``skip`` (Y) or ``fact_check`` (N)."""
    run = _run(services, run_id)
    if not run.decide(body.item_id, body.decision == "fact_check"):
        raise TypedHTTPError(409, "not_waiting", f"item {body.item_id} is not waiting at the gate")
    return {"ok": True, "item_id": body.item_id, "decision": body.decision}


class AutoSkipBody(BaseModel):
    on: bool


@router.post("/runs/{run_id}/auto-skip")
async def auto_skip(run_id: str, body: AutoSkipBody, services: ServicesDep) -> dict[str, Any]:
    run = _run(services, run_id)
    run.set_auto_skip(body.on)
    return {"ok": True, "auto_skip": body.on}


@router.post("/runs/{run_id}/{action}")
async def control(
    run_id: str, action: Literal["pause", "resume", "cancel"], services: ServicesDep
) -> dict[str, Any]:
    run = _run(services, run_id)
    {"pause": run.pause, "resume": run.resume, "cancel": run.cancel}[action]()
    return {"ok": True, "status": run.status}
