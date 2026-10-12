"""Corpus Explorer routes — ``/v1/corpus/*`` over the local Postgres chunk corpus.

Thin adapters over :mod:`notebooklm._app.corpus_explorer`,
:mod:`~notebooklm._app.corpus_mutations`, :mod:`~notebooklm._app.corpus_answer`,
:mod:`~notebooklm._app.corpus_agent`, :mod:`~notebooklm._app.artifact_ingest`
and :mod:`~notebooklm._app.sfl_tagging`. Every route sits behind the ``/v1``
bearer-token dependency; Postgres being down yields ``503
database_unreachable`` (see :mod:`.._corpus`).

This module imports NO ``click`` / ``rich`` / ``cli``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..._app import corpus_agent, corpus_answer, corpus_explorer, corpus_mutations
from ..._app.artifact_ingest import ingest_artifact, list_ingestible
from ..._app.corpus_explorer import ChunkNotFoundError, CorpusFilters
from ..._app.notebook_titles import stored_titles, upsert_titles
from ..._app.sfl_tagging import GroupProgress, load_children, tag_children
from ..._preprocessing.transcription import TranscriptionOptions, providers
from ...db.models import ChunkRun
from .._context import get_client
from .._corpus import (
    CorpusServices,
    TypedHTTPError,
    corpus_services,
    corpus_session,
    scope_from,
    sse_response,
)

__all__ = ["router"]

router = APIRouter(prefix="/corpus", tags=["corpus"])

SessionDep = Annotated[AsyncSession, Depends(corpus_session)]
ServicesDep = Annotated[CorpusServices, Depends(corpus_services)]

_LIST_FILTERS = (
    "notebook_ids",
    "document_ids",
    "run_ids",
    "external_ids",
    "strategies",
    "kinds",
    "fact_check",
    "quality",
)
_SCALAR_FILTERS = ("min_len", "max_len", "has_near_duplicate", "active_only", "text")


def filters_from_query(request: Request) -> CorpusFilters:
    """``?kinds=audio&kinds=report`` or ``?kinds=audio,report`` → :class:`CorpusFilters`."""
    params = request.query_params
    data: dict[str, Any] = {}
    for key in _LIST_FILTERS:
        values = [v for raw in params.getlist(key) for v in raw.split(",") if v]
        if values:
            data[key] = values
    for key in _SCALAR_FILTERS:
        if key in params and params[key] != "":
            data[key] = params[key]
    try:
        return CorpusFilters.from_mapping(data)
    except ValueError as e:
        raise TypedHTTPError(422, "validation", f"bad filter: {e}") from e


FiltersDep = Annotated[CorpusFilters, Depends(filters_from_query)]


def _filters(body: dict[str, Any] | None) -> CorpusFilters:
    try:
        return CorpusFilters.from_mapping(body)
    except (TypeError, ValueError) as e:
        raise TypedHTTPError(422, "validation", f"bad filter: {e}") from e


def _not_found(e: ChunkNotFoundError) -> TypedHTTPError:
    return TypedHTTPError(404, "not_found", f"no chunk {e.args[0]!r}")


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


@router.get("/stats")
async def stats(
    session: SessionDep,
    filters: FiltersDep,
    since: Annotated[int | None, Query(ge=0)] = None,
) -> dict[str, Any]:
    """Corpus counts; with ``since=<clause id>`` also how many chunks are newer."""
    out = await corpus_explorer.stats(session, filters)
    if since is not None:
        out["new_since"] = await corpus_explorer.count_new_since(session, since, filters)
    return out


@router.get("/facets")
async def facets(session: SessionDep, filters: FiltersDep) -> dict[str, Any]:
    return await corpus_explorer.facets(session, filters)


@router.get("/chunks")
async def browse(
    session: SessionDep,
    filters: FiltersDep,
    cursor: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=corpus_explorer.MAX_PAGE)] = corpus_explorer.DEFAULT_PAGE,
) -> dict[str, Any]:
    return await corpus_explorer.browse(session, filters, cursor=cursor, limit=limit)


@router.get("/chunks/{external_id}")
async def chunk_detail(external_id: str, session: SessionDep) -> dict[str, Any]:
    try:
        return await corpus_explorer.chunk_detail(session, external_id)
    except ChunkNotFoundError as e:
        raise _not_found(e) from e


@router.get("/chunks/{external_id}/neighbors")
async def neighbors(
    external_id: str,
    session: SessionDep,
    k: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict[str, Any]:
    try:
        items = await corpus_explorer.neighbors(session, external_id, k)
    except ChunkNotFoundError as e:
        raise _not_found(e) from e
    return {"items": items, "near_dup_threshold": corpus_explorer.NEAR_DUP_L2}


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    mode: Literal["keyword", "vector", "hybrid"] = "hybrid"
    filters: dict[str, Any] | None = None
    top_k: int = Field(default=25, ge=1, le=200)


@router.post("/search")
async def search(body: SearchBody, session: SessionDep, services: ServicesDep) -> dict[str, Any]:
    """Keyword / vector / hybrid-RRF search with per-leg ranks (LLM-free)."""
    return await corpus_explorer.search(
        session,
        body.query,
        mode=body.mode,
        filters=_filters(body.filters),
        top_k=body.top_k,
        embedder=services.embedder,
    )


@router.get("/runs")
async def runs(
    session: SessionDep,
    notebook_id: str | None = None,
    document_id: str | None = None,
    active_only: bool = False,
) -> dict[str, Any]:
    items = await corpus_explorer.runs(
        session, notebook_id=notebook_id, document_id=document_id, active_only=active_only
    )
    return {"items": items}


@router.get("/map")
async def corpus_map(
    session: SessionDep,
    filters: FiltersDep,
    method: Literal["pca", "umap"] = "pca",
) -> dict[str, Any]:
    return await corpus_explorer.map_points(session, method=method, filters=filters)


@router.get("/notebooks")
async def notebooks(request: Request, session: SessionDep) -> dict[str, Any]:
    """Notebooks present in the corpus, with chunk counts and (best effort) titles."""
    stmt = (
        select(ChunkRun.notebook_id, func.sum(ChunkRun.n_children), func.count(ChunkRun.id))
        .where(ChunkRun.is_active.is_(True), ChunkRun.notebook_id.is_not(None))
        .group_by(ChunkRun.notebook_id)
        .order_by(func.sum(ChunkRun.n_children).desc())
    )
    rows = (await session.execute(stmt)).all()
    titles = await stored_titles(session, [nb for nb, _, _ in rows])
    state = getattr(request.app.state, "notebooklm", None)
    client = getattr(state, "client", None)
    if client is not None:
        try:
            listed = await asyncio.wait_for(client.notebooks.list(), timeout=5)
            live = {
                nb.id: str(nb.title)
                for nb in listed
                if getattr(nb, "id", None) and getattr(nb, "title", None)
            }
            if live:
                await upsert_titles(session, live)
            titles.update(live)
        except Exception:  # noqa: BLE001 - a live failure keeps the stored titles
            pass
    return {
        "items": [
            {"id": nb, "title": titles.get(nb), "chunks": int(n or 0), "documents": int(d)}
            for nb, n, d in rows
        ]
    }


@router.get("/health")
async def health(request: Request, services: ServicesDep) -> dict[str, Any]:
    """Postgres, embedder, and running jobs — never 503s, so the footer can render."""
    pg: dict[str, Any]
    started = time.perf_counter()
    try:
        session = services.session_maker()
        try:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=3)
            pg = {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000)}
        finally:
            await session.close()
    except Exception as e:  # noqa: BLE001 - health must report, not raise
        pg = {"ok": False, "error": type(e).__name__}
    embedder = await services.embedder_health()
    jobs = [j.snapshot() for j in services.jobs.active()]
    runs = [{k: v for k, v in r.snapshot().items() if k != "items"} for r in services.runs.active()]
    return {"postgres": pg, "embedder": embedder, "jobs": jobs, "factcheck_runs": runs}


# ---------------------------------------------------------------------------
# Delete + export
# ---------------------------------------------------------------------------


class DeleteBody(BaseModel):
    level: Literal["clause", "parent", "document", "run"]
    ids: list[str] = Field(min_length=1, max_length=5000)
    reason: str = "other"


@router.post("/delete/preview")
async def delete_preview(body: DeleteBody, session: SessionDep) -> dict[str, Any]:
    """Counts per table that a delete would remove. Changes nothing."""
    try:
        return await corpus_mutations.delete_preview(session, body.level, body.ids, body.reason)
    except ValueError as e:
        raise TypedHTTPError(422, "validation", str(e)) from e


@router.post("/delete")
async def delete(body: DeleteBody, session: SessionDep, services: ServicesDep) -> dict[str, Any]:
    """Hard delete (only after the UI's confirm step) with ``removal_log`` audit rows."""
    try:
        receipt = await corpus_mutations.delete(
            session,
            body.level,
            body.ids,
            body.reason,
            busy_document_ids=services.jobs.busy_document_ids(),
        )
    except corpus_mutations.DeleteRefusedError as e:
        raise TypedHTTPError(409, "busy", str(e)) from e
    except ValueError as e:
        raise TypedHTTPError(422, "validation", str(e)) from e
    return receipt.to_dict()


class ExportBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)
    format: Literal["markdown", "json"] = "markdown"


@router.post("/export")
async def export(body: ExportBody, session: SessionDep) -> Response:
    out = await corpus_mutations.export(session, body.ids, body.format)
    return Response(
        content=out["content"],
        media_type=out["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{out["filename"]}"',
            "X-Export-Count": str(out["count"]),
        },
    )


class NoteBody(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=2000)
    title: str | None = None


@router.post("/export/note")
async def export_note(
    body: NoteBody, session: SessionDep, client: Annotated[Any, Depends(get_client)]
) -> dict[str, Any]:
    try:
        created = await corpus_mutations.export_to_note(client, session, body.ids, body.title)
    except ValueError as e:
        raise TypedHTTPError(422, "validation", str(e)) from e
    return {"notes": created}


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------


class AnswerBody(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    mode: Literal["auto", "notebooklm", "agent", "deep", "model"] = "auto"
    model: str | None = None
    #: Explicit chunks to ground on; otherwise the question is searched.
    ids: list[str] | None = None
    filters: dict[str, Any] | None = None
    top_k: int = Field(default=8, ge=1, le=50)
    notebook_id: str | None = None


async def _hits(body: AnswerBody, session: AsyncSession, services: CorpusServices) -> list[Any]:
    if body.ids:
        rows = await corpus_explorer.browse(
            session, CorpusFilters(external_ids=body.ids, active_only=False), limit=len(body.ids)
        )
        order = {eid: i for i, eid in enumerate(body.ids)}
        return sorted(rows["items"], key=lambda r: order.get(r["external_id"], 0))
    result = await corpus_explorer.search(
        session,
        body.question,
        filters=_filters(body.filters),
        top_k=body.top_k,
        embedder=services.embedder,
    )
    return list(result["hits"])


def _agent_tools(services: CorpusServices, client: Any) -> corpus_agent.CorpusTools:
    async def search_tool(query: str) -> list[dict[str, Any]]:
        async with services.session_maker() as s:
            return list(
                (await corpus_explorer.search(s, query, top_k=8, embedder=services.embedder))[
                    "hits"
                ]
            )

    async def detail_tool(external_id: str) -> dict[str, Any]:
        async with services.session_maker() as s:
            return await corpus_explorer.chunk_detail(s, external_id)

    async def neighbors_tool(external_id: str) -> list[dict[str, Any]]:
        async with services.session_maker() as s:
            return await corpus_explorer.neighbors(s, external_id, 5)

    async def ask_tool(notebook_id: str, question: str) -> str:
        if client is None:
            return "NotebookLM is not signed in."
        result = await client.chat.ask(notebook_id, question)
        return str(getattr(result, "answer", ""))

    return corpus_agent.CorpusTools(search_tool, detail_tool, neighbors_tool, ask_tool)


async def _client_or_none(request: Request) -> Any:
    try:
        return await get_client(request)
    except Exception:  # noqa: BLE001 - only the NotebookLM modes need the client
        return None


@router.post("/answer", response_model=None)
async def answer(
    body: AnswerBody, request: Request, session: SessionDep, services: ServicesDep
) -> Any:
    """Answer grounded in retrieved chunks.

    ``mode``: ``notebooklm`` (one notebook, ``chat.ask``), ``agent`` (DSPy
    cross-notebook pipeline), ``deep`` (experimental ``dspy.RLM``), ``model``
    (any litellm model, streamed over SSE), or ``auto`` (agent when the hits
    span notebooks, else NotebookLM).
    """
    hits = await _hits(body, session, services)
    await session.close()
    if not hits:
        raise TypedHTTPError(404, "no_hits", "no chunks matched; nothing to ground an answer in")
    mode = body.mode
    if mode == "auto":
        mode = "agent" if len(corpus_answer.notebooks_of(hits)) > 1 else "notebooklm"

    if mode == "model":
        if not body.model:
            raise TypedHTTPError(422, "validation", "mode=model needs a litellm model string")
        model = body.model
        _, labels = corpus_answer.build_prompt(body.question, hits)

        async def events() -> AsyncIterator[dict[str, Any]]:
            yield {"type": "hits", "hits": hits, "labels": labels, "mode": "model"}
            parts: list[str] = []
            try:
                async for token in corpus_answer.answer_litellm(
                    model, body.question, hits, completion=services.completion
                ):
                    parts.append(token)
                    yield {"type": "token", "text": token}
            except Exception as e:  # noqa: BLE001 - streamed to the client as an event
                yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
                return
            full = "".join(parts)
            yield {
                "type": "done",
                "answer": full,
                "citations": corpus_answer.citation_map(full, labels),
            }

        return sse_response(events())

    try:
        if mode == "notebooklm":
            client = await get_client(request)
            out = await corpus_answer.answer_notebooklm(
                client, body.question, hits, notebook_id=body.notebook_id
            )
        elif mode == "agent":
            kwargs: dict[str, Any] = {}
            if services.react_factory is not None:
                kwargs["react_factory"] = services.react_factory
            if services.mcc_factory is not None:
                kwargs["mcc_factory"] = services.mcc_factory
            out = await corpus_agent.answer_corpus(
                body.question,
                hits,
                _agent_tools(services, await _client_or_none(request)),
                lm=services.lm,
                **kwargs,
            )
        else:
            out = await corpus_agent.answer_deep(
                body.question,
                hits,
                lm=services.lm,
                rlm_factory=services.rlm_factory,
                sandbox_check=services.deep_sandbox_check,
            )
    except corpus_agent.DeepModeUnavailableError as e:
        raise TypedHTTPError(409, "deep_mode_unavailable", str(e)) from e
    except corpus_agent.AgentUnavailableError as e:
        raise TypedHTTPError(503, "llm_unavailable", str(e)) from e
    except ValueError as e:
        raise TypedHTTPError(422, "validation", str(e)) from e
    return {**out, "hits": hits}


# ---------------------------------------------------------------------------
# Artifacts, transcription providers, SFL runs, jobs
# ---------------------------------------------------------------------------


@router.get("/transcription/providers")
async def transcription_providers() -> dict[str, Any]:
    return {"providers": providers(), "defaults": TranscriptionOptions.from_env().to_dict()}


@router.get("/artifacts")
async def artifacts(
    notebook_id: str, session: SessionDep, client: Annotated[Any, Depends(get_client)]
) -> dict[str, Any]:
    return {"items": await list_ingestible(client, notebook_id, session)}


class IngestBody(BaseModel):
    notebook_id: str
    provider: str | None = None
    diarize: bool | None = None
    language: str | None = None
    force: bool = False


async def _notebook_title(client: Any, notebook_id: str) -> str | None:
    """Best-effort live title: ``notebooks.get`` first, then the list."""
    get = getattr(client.notebooks, "get", None)
    if get is not None:
        try:
            nb = await asyncio.wait_for(get(notebook_id), timeout=5)
            return getattr(nb, "title", None) or None
        except Exception:  # noqa: BLE001 - fall back to the list
            pass
    try:
        listed = await asyncio.wait_for(client.notebooks.list(), timeout=5)
    except Exception:  # noqa: BLE001 - the title is decoration only
        return None
    for nb in listed:
        if getattr(nb, "id", None) == notebook_id:
            return getattr(nb, "title", None) or None
    return None


@router.post("/artifacts/{artifact_id}/ingest", status_code=202)
async def ingest(
    artifact_id: str,
    body: IngestBody,
    services: ServicesDep,
    client: Annotated[Any, Depends(get_client)],
) -> dict[str, Any]:
    """Start a background ingest of one artifact (progress via ``/corpus/jobs/{id}/events``)."""
    try:
        title = await _notebook_title(client, body.notebook_id)
        if title:
            async with services.session_maker() as session:
                await upsert_titles(session, {body.notebook_id: title})
    except Exception:  # noqa: BLE001 - ingest proceeds without a stored title
        pass
    defaults = TranscriptionOptions.from_env()
    language = body.language if body.language is not None else defaults.language
    options = TranscriptionOptions(
        provider=(body.provider or defaults.provider).lower(),
        diarize=defaults.diarize if body.diarize is None else body.diarize,
        language=None if (language or "auto").lower() == "auto" else language,
    )

    async def run(job: Any) -> Any:
        async with services.session_maker() as session:
            return await ingest_artifact(
                client,
                session,
                body.notebook_id,
                artifact_id,
                service=services.ingest_service_factory(client),
                options=options,
                force=body.force,
                transcriber=services.transcriber,
                progress=job.progress,
                cache_dir=services.transcript_cache,
            )

    job = services.jobs.start(
        "ingest", f"ingest artifact {artifact_id}", run, document_ids={artifact_id}
    )
    return job.snapshot()


class SflBody(BaseModel):
    scope: dict[str, Any]


@router.post("/sfl/runs", status_code=202)
async def sfl_run(body: SflBody, services: ServicesDep) -> dict[str, Any]:
    """Tag SFL for any scope (documents, runs, chunks or a notebook) in the background."""
    scope = scope_from(body.scope)
    label = f"SFL tag {scope.describe()}"
    for existing in services.jobs.active():
        if existing.kind == "sfl_tag" and existing.label == label:
            return existing.snapshot()

    async def run(job: Any) -> Any:
        children = await load_children(services.session_maker, scope)  # type: ignore[arg-type]
        if not children:
            raise RuntimeError("no ingested children in scope")
        job.progress("tagging", 0, len(children))
        tagged_so_far = 0

        def start(number: int, total: int, parent_index: int, n_children: int) -> int:
            job.progress(f"parent {number}/{total}", tagged_so_far)
            return n_children

        def done(handle: int, n_children: int, n_failed: int, first_error: str | None) -> None:
            nonlocal tagged_so_far
            tagged_so_far += n_children
            job.progress(
                f"{n_failed} failed: {first_error}" if first_error else "parent done",
                tagged_so_far,
            )

        tagged, failed = await tag_children(
            children,
            session_factory=services.session_maker,  # type: ignore[arg-type]
            progress=GroupProgress(start=start, done=done),
            engine=services.sfl_engine_factory(),
            lm=services.lm,
        )
        return {"tagged": tagged, "failed": failed}

    job = services.jobs.start("sfl_tag", f"SFL tag {scope.describe()}", run)
    return job.snapshot()


@router.get("/jobs")
async def jobs(services: ServicesDep) -> dict[str, Any]:
    return {"items": [j.snapshot() for j in services.jobs.all()]}


@router.get("/jobs/{job_id}")
async def job(job_id: str, services: ServicesDep) -> dict[str, Any]:
    found = services.jobs.get(job_id)
    if found is None:
        raise TypedHTTPError(404, "not_found", f"no job {job_id!r}")
    return found.snapshot()


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str, services: ServicesDep, after: Annotated[int, Query(ge=0)] = 0
) -> Any:
    found = services.jobs.get(job_id)
    if found is None:
        raise TypedHTTPError(404, "not_found", f"no job {job_id!r}")
    return sse_response(found.subscribe(after))
