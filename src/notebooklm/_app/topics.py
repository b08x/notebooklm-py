"""BERTopic fitting over stored child embeddings, and persistence of the result.

Documents are never re-embedded: :func:`fit_topics` passes the stored vectors to
BERTopic with ``embedding_model=None``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ChunkRun, Clause, Embedding, Topic, TopicRun

#: Number of keywords kept per topic.
KEYWORD_COUNT = 10


def fit_topics(
    docs: list[str],
    vectors: list[list[float]],
    *,
    min_topic_size: int = 10,
    umap_kwargs: dict[str, Any] | None = None,
    hdbscan_kwargs: dict[str, Any] | None = None,
) -> tuple[list[int], list[dict[str, Any]]]:
    """Cluster ``docs`` by their precomputed ``vectors`` with BERTopic.

    Returns the topic number of each document (``-1`` is the outlier bucket) and
    one dict per topic: ``topic_number``, ``label``, ``keywords`` and ``size``.
    """
    import numpy as np
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from umap import UMAP

    umap_args: dict[str, Any] = {
        "n_neighbors": max(2, min(15, len(docs) - 1)),
        "n_components": 5,
        "min_dist": 0.0,
        "metric": "cosine",
        "low_memory": True,
        "random_state": 42,
    }
    umap_args.update(umap_kwargs or {})
    hdbscan_args: dict[str, Any] = {
        "min_cluster_size": min_topic_size,
        "metric": "euclidean",
        "cluster_selection_method": "eom",
        "prediction_data": True,
    }
    hdbscan_args.update(hdbscan_kwargs or {})

    model = BERTopic(
        embedding_model=None,
        umap_model=UMAP(**umap_args),
        hdbscan_model=HDBSCAN(**hdbscan_args),
        min_topic_size=min_topic_size,
        verbose=False,
    )
    topic_numbers, _ = model.fit_transform(docs, embeddings=np.asarray(vectors))

    info = model.get_topic_info()
    topics: list[dict[str, Any]] = []
    for row in info.itertuples(index=False):
        number = int(row.Topic)
        keywords = [str(word) for word, _ in (model.get_topic(number) or [])][:KEYWORD_COUNT]
        topics.append(
            {
                "topic_number": number,
                "label": str(row.Name),
                "keywords": keywords,
                "size": int(row.Count),
            }
        )
    return [int(t) for t in topic_numbers], topics


async def load_corpus(session: AsyncSession) -> tuple[list[str], list[str], list[list[float]]]:
    """Return ``(clause_external_ids, texts, vectors)`` for every child of an active run."""
    stmt = (
        select(Clause.external_id, Clause.text, Embedding.embedding)
        .join(ChunkRun, Clause.run_id == ChunkRun.id)
        .join(Embedding, Embedding.clause_id == Clause.external_id)
        .where(ChunkRun.is_active.is_(True))
        .order_by(Clause.external_id)
    )
    ids: list[str] = []
    texts: list[str] = []
    vectors: list[list[float]] = []
    seen: set[str] = set()
    for external_id, text, embedding in (await session.execute(stmt)).all():
        if external_id in seen:
            continue
        seen.add(external_id)
        ids.append(external_id)
        texts.append(text)
        vectors.append([float(x) for x in embedding])
    return ids, texts, vectors


async def save_topics(
    session: AsyncSession,
    params: dict[str, Any],
    trace_id: str | None,
    topic_numbers: Sequence[int],
    topics: Sequence[dict[str, Any]],
    clause_ids: Sequence[str],
) -> int:
    """Write a ``TopicRun``, its ``Topic`` rows and each child's ``topic_id``; return the run id."""
    if len(topic_numbers) != len(clause_ids):
        raise ValueError("topic_numbers and clause_ids differ in length")
    run = TopicRun(
        params=params,
        n_docs=len(clause_ids),
        n_topics=sum(1 for t in topics if t["topic_number"] != -1),
        trace_id=trace_id,
    )
    session.add(run)
    await session.flush()

    topic_rows: dict[int, int] = {}
    for t in topics:
        row = Topic(
            run_id=run.id,
            topic_number=int(t["topic_number"]),
            label=t["label"],
            keywords=list(t["keywords"]),
            size=int(t["size"]),
        )
        session.add(row)
        await session.flush()
        topic_rows[row.topic_number] = row.id

    by_number: dict[int, list[str]] = {}
    for number, clause_id in zip(topic_numbers, clause_ids, strict=True):
        by_number.setdefault(int(number), []).append(clause_id)
    for number, ids in by_number.items():
        await session.execute(
            update(Clause).where(Clause.external_id.in_(ids)).values(topic_id=topic_rows[number])
        )
    await session.commit()
    return int(run.id)
