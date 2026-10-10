"""``ingest`` job handler: chunk a notebook's sources and notes into a new run.

Payload: ``strategy`` (registry name, default ``recursive``), ``params`` (strategy
kwargs), ``source_ids`` (subset to ingest, or ``None`` for all), ``context``
(embedding-context override; ``None`` resolves NotebookLM's own summaries).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from ....client import NotebookLMClient
from ....db.session import async_session_maker
from ..runner import JobContext

logger = logging.getLogger(__name__)


def _default_service(client: Any, strategy: Any) -> Any:
    from ...._preprocessing.ingestion import IngestionService

    return IngestionService(client, strategy=strategy)


def _make_strategy(name: str, params: dict[str, Any]) -> Any:
    from ...._preprocessing.chunking import make_strategy

    return make_strategy(name, **params)


async def run_ingest(
    ctx: JobContext,
    *,
    client_factory: Callable[[], Any] = NotebookLMClient.from_storage,
    session_factory: Callable[[], Any] = async_session_maker,
    service_factory: Callable[[Any, Any], Any] = _default_service,
    strategy_factory: Callable[[str, dict[str, Any]], Any] = _make_strategy,
) -> str:
    notebook_id = ctx.notebook_id
    if not notebook_id:
        raise ValueError("ingest job requires a notebook id")
    payload = ctx.payload
    strategy_name = payload.get("strategy") or "recursive"
    strategy = strategy_factory(strategy_name, payload.get("params") or {})
    source_ids = payload.get("source_ids")
    wanted = set(source_ids) if source_ids is not None else None
    context = payload.get("context")

    ctx.phase("Listing sources", 0)
    async with client_factory() as client:
        await ctx.acquire_token()
        sources = await client.sources.list(notebook_id)
        await ctx.acquire_token()
        try:
            notes = await client.notes.list(notebook_id)
        except Exception:
            notes = []
        docs = [("source", s) for s in sources] + [("note", n) for n in notes]
        if wanted is not None:
            docs = [(kind, d) for kind, d in docs if d.id in wanted]

        service = service_factory(client, strategy)
        items = [
            (ctx.add_item(getattr(d, "title", None) or d.id, kind), kind, d) for kind, d in docs
        ]
        total_children = 0
        failed = 0
        for n, (item_id, kind, doc) in enumerate(items):
            ctx.check_cancelled()
            ctx.item_running(item_id)
            title = getattr(doc, "title", None) or doc.id
            ctx.phase(f"Ingesting {title}", 100 * n / len(items))
            try:
                async with session_factory() as session:
                    if kind == "note":
                        count = await service.ingest_text(
                            session,
                            document_id=doc.id,
                            text=getattr(doc, "content", None) or "",
                            notebook_id=notebook_id,
                            context=context,
                        )
                    else:
                        await ctx.acquire_token()
                        count = await service.ingest_source(
                            session, notebook_id, doc.id, context=context
                        )
            except Exception as e:
                logger.exception("Ingestion failed for %s", doc.id)
                ctx.item_failed(item_id, f"{type(e).__name__}: {e}")
                failed += 1
                continue
            total_children += count
            if count:
                ctx.item_done(item_id)
            else:
                ctx.item_skipped(item_id, "no text")

    summary = f"Ingested {total_children} children from {len(items)} documents ({strategy_name})"
    if failed:
        summary += f"; {failed} failed"
    return summary


async def handle(ctx: JobContext) -> str | None:
    return await run_ingest(ctx)
