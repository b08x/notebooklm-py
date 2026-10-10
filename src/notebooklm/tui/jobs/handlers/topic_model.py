"""``topic_model`` job handler: BERTopic over the stored children of the active corpus."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from ...._app.topics import fit_topics, load_corpus, save_topics
from ....db.session import async_session_maker
from ..runner import JobContext

DEFAULT_MIN_TOPIC_SIZE = 10


async def run_topic_model(
    ctx: JobContext,
    *,
    session_factory: Callable[[], Any] = async_session_maker,
    load: Callable[[Any], Awaitable[tuple[list[str], list[str], list[list[float]]]]] = load_corpus,
    fit: Callable[..., tuple[list[int], list[dict[str, Any]]]] = fit_topics,
    save: Callable[..., Awaitable[int]] = save_topics,
) -> str:
    """Load the corpus, fit topics off the event loop, and write the topic run."""
    min_topic_size = int(ctx.payload.get("min_topic_size", DEFAULT_MIN_TOPIC_SIZE))
    params = {"min_topic_size": min_topic_size}

    load_item = ctx.add_item("load children", "load")
    ctx.item_running(load_item)
    ctx.phase("loading children", 5)
    async with session_factory() as session:
        clause_ids, texts, vectors = await load(session)
    if not texts:
        ctx.item_failed(load_item, "no active children")
        raise RuntimeError("no ingested children; run ingest first")
    ctx.item_done(load_item)
    ctx.check_cancelled()

    fit_item = ctx.add_item(f"fit {len(texts)} children", "fit")
    ctx.item_running(fit_item)
    ctx.phase("fitting topics", 30)
    topic_numbers, topics = await asyncio.to_thread(
        fit, texts, vectors, min_topic_size=min_topic_size
    )
    ctx.item_done(fit_item)
    ctx.check_cancelled()

    write_item = ctx.add_item("write topics", "write")
    ctx.item_running(write_item)
    ctx.phase("writing topics", 85)
    async with session_factory() as session:
        await save(session, params, ctx.trace_id, topic_numbers, topics, clause_ids)
    ctx.item_done(write_item)

    n_topics = sum(1 for t in topics if t["topic_number"] != -1)
    return f"{n_topics} topics over {len(texts)} children"


async def handle(ctx: JobContext) -> str | None:
    return await run_topic_model(ctx)
