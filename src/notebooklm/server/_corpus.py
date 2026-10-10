"""Shared plumbing for the ``/v1/corpus`` routes: services, DB sessions, SSE.

:class:`CorpusServices` is the injection seam for everything the Corpus
Explorer routes touch besides the NotebookLM client — the Postgres session
maker, embedder, fact checker, Jev client, ingestion service, transcriber, SFL
engine and the run/job registries. ``create_app(corpus_services=...)`` lets
tests swap any of them.

**Database unreachable → 503.** :func:`corpus_session` checks a connection out
before the route runs; any failure to connect raises
:class:`DatabaseUnavailableError`, projected onto ``503`` with category
``database_unreachable`` — the UI then shows a blocking screen, never an empty
corpus.

This module imports NO ``click`` / ``rich`` / ``cli``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .._app.background import JobRegistry
from .._app.corpus_agent import deno_available
from .._app.corpus_explorer import embedder_health
from .._app.factcheck_runs import RunRegistry
from .._app.scope import Scope
from ..db.session import async_session_maker

logger = logging.getLogger(__name__)

__all__ = [
    "CorpusServices",
    "DatabaseUnavailableError",
    "TypedHTTPError",
    "configure_llm_on_main_thread",
    "corpus_services",
    "corpus_session",
    "install_corpus_handlers",
    "sse_response",
]

#: Seconds between SSE keep-alive comments.
SSE_KEEPALIVE = 15.0


def _default_checker() -> Any:
    from .._preprocessing.sift import SiftChecker

    return SiftChecker()


def _default_jev() -> Any:
    from .._preprocessing.jev import JevClient

    return JevClient()


def _default_ingest_service(client: Any) -> Any:
    from .._preprocessing.ingestion import IngestionService

    return IngestionService(client)


def _default_transcriber(path: str, options: Any) -> dict[str, Any]:
    from .._app.artifact_ingest import default_transcriber

    return default_transcriber(path, options)


def _default_sfl_engine() -> Any:
    from .._app.sfl_tagging import default_engine

    return default_engine()


@dataclass
class CorpusServices:
    """Everything the corpus routes use besides the NotebookLM client."""

    session_maker: Callable[[], AsyncSession] = async_session_maker
    embedder: Any = None
    checker_factory: Callable[[], Any] = _default_checker
    jev_factory: Callable[[], Any] = _default_jev
    ingest_service_factory: Callable[[Any], Any] = _default_ingest_service
    transcriber: Callable[[str, Any], dict[str, Any]] = _default_transcriber
    sfl_engine_factory: Callable[[], Any] = _default_sfl_engine
    #: ``None`` = ``dspy.settings.lm`` (configured once at startup).
    lm: Any = None
    react_factory: Any = None
    mcc_factory: Any = None
    rlm_factory: Any = None
    deep_sandbox_check: Callable[[], bool] = deno_available
    #: ``litellm.acompletion`` stand-in for streamed model answers.
    completion: Any = None
    embedder_health: Callable[[], Any] = embedder_health
    #: Whether the lifespan configures the DSPy LM (main thread only).
    configure_llm: bool = True
    #: Transcript cache dir for artifact ingest (``True`` = default dir).
    transcript_cache: Any = True
    runs: RunRegistry = field(default_factory=RunRegistry)
    jobs: JobRegistry = field(default_factory=JobRegistry)


def corpus_services(request: Request) -> CorpusServices:
    services: CorpusServices = request.app.state.corpus
    return services


class DatabaseUnavailableError(RuntimeError):
    """Postgres could not be reached."""


class TypedHTTPError(Exception):
    """An error with its own ``category`` (e.g. ``sfl_required``) and status."""

    def __init__(self, status: int, category: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.category = category
        self.message = message
        self.extra = extra


def typed_error_response(status: int, category: str, message: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"category": category, "message": message[:500], **extra}},
    )


async def corpus_session(request: Request) -> AsyncIterator[AsyncSession]:
    """A session whose connection is already checked out (503 if Postgres is down)."""
    session = corpus_services(request).session_maker()
    try:
        try:
            await session.connection()
        except Exception as e:  # noqa: BLE001 - any connect failure means unreachable
            raise DatabaseUnavailableError(f"{type(e).__name__}: {e}") from e
        yield session
    finally:
        try:
            await session.close()
        except Exception:  # noqa: BLE001 - closing a dead connection must not mask the error
            logger.debug("closing corpus session failed", exc_info=True)


def install_corpus_handlers(app: FastAPI) -> None:
    @app.exception_handler(DatabaseUnavailableError)
    async def _db_down(_request: Request, exc: DatabaseUnavailableError) -> JSONResponse:
        return typed_error_response(
            503,
            "database_unreachable",
            "Postgres is unreachable; start it (deploy/docker-compose.db.yml) and retry.",
            retriable=True,
        )

    @app.exception_handler(TypedHTTPError)
    async def _typed(_request: Request, exc: TypedHTTPError) -> JSONResponse:
        return typed_error_response(exc.status, exc.category, exc.message, **exc.extra)


def configure_llm_on_main_thread(services: CorpusServices) -> bool:
    """Configure the DSPy LM once, only when running on the main thread.

    ``dspy.configure()`` makes its calling thread the owner; workers then bind
    ``dspy.context(lm=dspy.settings.lm)``. Off the main thread (e.g. an ASGI
    test client's portal thread) this is skipped.
    """
    if not services.configure_llm:
        return False
    if threading.current_thread() is not threading.main_thread():
        logger.info("Skipping DSPy LM setup: lifespan is not on the main thread")
        return False
    try:
        from .._app.assessment import setup_dspy_router

        setup_dspy_router()
        return True
    except Exception as e:  # noqa: BLE001 - LLM features degrade; search still works
        logger.warning("DSPy LM setup failed (%s); LLM features unavailable", e)
        return False


def scope_from(data: dict[str, Any] | None) -> Scope:
    scope = Scope.from_mapping(data)
    if scope.is_empty:
        raise TypedHTTPError(422, "validation", "scope needs a notebook, documents, runs or chunks")
    return scope


def _sse(event: dict[str, Any]) -> str:
    seq = event.get("seq")
    head = f"id: {seq}\n" if seq is not None else ""
    return (
        f"{head}event: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"
    )


def sse_response(events: AsyncIterator[dict[str, Any]]) -> StreamingResponse:
    """Stream ``events`` as Server-Sent Events, with keep-alive comments."""

    async def body() -> AsyncIterator[str]:
        it = events.__aiter__()
        pending: asyncio.Task[dict[str, Any]] | None = None
        try:
            while True:
                if pending is None:
                    pending = asyncio.ensure_future(it.__anext__())
                done, _ = await asyncio.wait({pending}, timeout=SSE_KEEPALIVE)
                if not done:
                    yield ": keep-alive\n\n"
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    return
                finally:
                    pending = None
                yield _sse(event)
        finally:
            if pending is not None:
                pending.cancel()

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
