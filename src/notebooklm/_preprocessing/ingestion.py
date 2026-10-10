import asyncio
import hashlib
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app.tracing import current_trace_id
from notebooklm._preprocessing.chunking import (
    ChildChunk,
    ChunkResult,
    ChunkStats,
    ChunkStrategy,
    ParentChunk,
)
from notebooklm._preprocessing.embeddings import EmbeddingAdapter, OllamaEmbeddingAdapter
from notebooklm._preprocessing.features import ClauseFeatures, extract
from notebooklm.db.models import ChunkRun, Clause, Embedding
from notebooklm.db.models import ParentChunk as ParentChunkRow

logger = logging.getLogger(__name__)


async def resolve_notebook_context(client: Any, notebook_id: str) -> str | None:
    """Fetch NotebookLM's own AI-generated notebook summary for contextual embedding."""
    try:
        summary = await client.notebooks.get_summary(notebook_id)
        if isinstance(summary, str):
            return summary.strip() or None
    except Exception:
        logger.warning("Could not fetch notebook summary for contextual embedding", exc_info=True)
    return None


async def resolve_source_context(client: Any, notebook_id: str, source_id: str) -> str | None:
    """Fetch NotebookLM's own AI-generated source summary for contextual embedding.

    Reusing it as a per-chunk context prefix avoids a separate paid per-chunk LLM
    call to generate that context. Best-effort: returns ``None`` on an empty
    summary or a failed fetch, so ingestion can proceed without it.
    """
    try:
        guide = await client.sources.get_guide(notebook_id, source_id)
        if hasattr(guide, "summary") and isinstance(guide.summary, str):
            return guide.summary.strip() or None
    except Exception:
        logger.warning("Could not fetch source summary for contextual embedding", exc_info=True)
    return None


#: ``chunk_runs.strategy`` for chunks a caller produced itself (``ingest_chunks``).
PROVIDED_STRATEGY = "provided"
PROVIDED_VERSION = "1"


@dataclass
class IngestResult:
    run_id: int
    #: Child ``Clause.external_id`` values in document order.
    external_ids: list[str] = field(default_factory=list)

    @property
    def n_children(self) -> int:
        return len(self.external_ids)


def _p95(values: list[int]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return float(ordered[min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1)])


def _default_strategy() -> ChunkStrategy:
    from notebooklm._preprocessing.chunking.recursive import RecursiveSplitter

    return RecursiveSplitter()


def _provided_result(text_chunks: list[str]) -> tuple[str, ChunkResult]:
    """One parent and one child per caller-supplied chunk, joined by blank lines."""
    parents: list[ParentChunk] = []
    pieces: list[str] = []
    offset = 0
    for chunk in text_chunks:
        start, end = offset, offset + len(chunk)
        parents.append(ParentChunk(chunk, start, end, [ChildChunk(chunk, start, end)]))
        pieces.append(chunk)
        offset = end + 2
    return "\n\n".join(pieces), ChunkResult(parents=parents, stats=ChunkStats())


class IngestionService:
    """Chunks text into parents/children and persists one ``chunk_runs`` run.

    :meth:`ingest_source` fetches full text from the NotebookLM API (or the local
    download cache); :meth:`ingest_text` runs a :class:`ChunkStrategy` over any
    resolved text; :meth:`ingest_chunks` stores caller-produced chunks 1:1
    (audio transcript turns). Every call writes a new run: ``parent_chunks``,
    child ``clauses`` (``external_id`` = ``{document_id}:{run_id}:{index}``) with
    spaCy features, and embeddings for children only. The new run becomes the
    document's active run; older runs are kept for comparison.

    Chunks are embedded with the source's summary prepended as context
    (``resolve_source_context``), unless ``use_source_context=False`` or a caller
    passes its own ``context`` (``""`` forces none). The prefix is embedding
    input only — ``Clause.text`` stores the unprefixed chunk. A strategy that
    returns precomputed vectors (cluster-semantic) is reused only when no
    context prefix applies, so all stored vectors share one embedding input
    format per run.
    """

    def __init__(
        self,
        client: Any,
        embedder: EmbeddingAdapter | None = None,
        strategy: ChunkStrategy | None = None,
        embedding_model_name: str = "embeddinggemma-300m",
        use_source_context: bool = True,
        embed_batch_size: int = 32,
        use_notebook_context: bool | None = None,
        nlp: Any | None = None,
        features: Callable[[list[str]], list[ClauseFeatures]] | None = None,
    ):
        self.client = client
        self.embedder = embedder or OllamaEmbeddingAdapter()
        self.strategy = strategy
        self.embedding_model_name = embedding_model_name
        self.use_source_context = (
            use_notebook_context if use_notebook_context is not None else use_source_context
        )
        #: A single ``/api/embed`` request holds all its texts in memory for the
        #: whole round trip; capping the batch bounds any one request's duration.
        self.embed_batch_size = embed_batch_size
        self._features = features or (lambda texts: extract(texts, nlp))

    @property
    def use_notebook_context(self) -> bool:
        return self.use_source_context

    @use_notebook_context.setter
    def use_notebook_context(self, value: bool) -> None:
        self.use_source_context = value

    async def _resolve_context(
        self, notebook_id: str, source_id: str, explicit_context: str | None
    ) -> str | None:
        if explicit_context is not None:
            return explicit_context.strip() or None
        if not self.use_source_context:
            return None
        source_ctx = await resolve_source_context(self.client, notebook_id, source_id)
        if source_ctx:
            return source_ctx
        return await resolve_notebook_context(self.client, notebook_id)

    async def ingest_source(
        self,
        session: AsyncSession,
        notebook_id: str,
        source_id: str,
        *,
        context: str | None = None,
        strategy: ChunkStrategy | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Chunk, embed, and persist one source's text. Returns children written."""
        import os

        from sqlalchemy import select

        from notebooklm.db.models import LocalAsset

        result = await session.execute(select(LocalAsset).where(LocalAsset.asset_id == source_id))
        local_asset = result.scalar_one_or_none()
        if local_asset and os.path.exists(local_asset.local_path):
            with open(local_asset.local_path, encoding="utf-8") as f:
                content = f.read()
        else:
            fulltext = await self.client.sources.get_fulltext(notebook_id, source_id)
            content = fulltext.content

        resolved_context = await self._resolve_context(notebook_id, source_id, context)
        return await self.ingest_text(
            session,
            document_id=source_id,
            text=content,
            notebook_id=notebook_id,
            context=resolved_context,
            strategy=strategy,
            on_progress=on_progress,
        )

    async def ingest_text(
        self,
        session: AsyncSession,
        document_id: str,
        text: str,
        *,
        notebook_id: str | None = None,
        context: str | None = None,
        strategy: ChunkStrategy | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Chunk ``text`` with ``strategy`` and persist a run. Returns children written."""
        result = await self.ingest_document(
            session,
            document_id,
            text,
            notebook_id=notebook_id,
            context=context,
            strategy=strategy,
            on_progress=on_progress,
        )
        return result.n_children if result else 0

    async def ingest_chunks(
        self,
        session: AsyncSession,
        document_id: str,
        chunks: list[str],
        *,
        notebook_id: str | None = None,
        context: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        params: dict[str, Any] | None = None,
    ) -> IngestResult | None:
        """Persist caller-produced chunks 1:1 as parent+child pairs.

        ``params`` is merged into the run's ``chunk_runs.params`` (e.g.
        ``{"kind": "audio", "artifact_id": ..., "title": ...}``).

        Used for audio transcripts, whose turns are already the units the
        assessment pipeline keys its results to. Returns the run (with child
        external ids in chunk order), or ``None`` when every chunk is blank.
        """
        kept = [c for c in chunks if c.strip()]
        if not kept:
            logger.info("Document %s produced no clauses to ingest", document_id)
            return None
        text, chunked = _provided_result(kept)
        return await self._persist(
            session,
            document_id,
            text,
            chunked,
            strategy_name=PROVIDED_STRATEGY,
            strategy_version=PROVIDED_VERSION,
            params=dict(params or {}),
            notebook_id=notebook_id,
            context=context,
            on_progress=on_progress,
        )

    async def ingest_document(
        self,
        session: AsyncSession,
        document_id: str,
        text: str,
        *,
        notebook_id: str | None = None,
        context: str | None = None,
        strategy: ChunkStrategy | None = None,
        on_progress: Callable[[int, int], None] | None = None,
        params: dict[str, Any] | None = None,
    ) -> IngestResult | None:
        """Run ``strategy`` (default recursive) over ``text`` and persist the run.

        ``params`` is merged over the strategy's own params in ``chunk_runs.params``.
        """
        strat = strategy or self.strategy or _default_strategy()
        # to_thread copies contextvars, so an LM bound by the job runner's
        # dspy.context reaches the strategy (dynamic-window needs it).
        chunked = await asyncio.to_thread(strat.chunk, text)
        if not any(p.children for p in chunked.parents):
            logger.info("Document %s produced no clauses to ingest", document_id)
            return None
        return await self._persist(
            session,
            document_id,
            text,
            chunked,
            strategy_name=strat.name,
            strategy_version=strat.version,
            params={**dict(strat.params), **(params or {})},
            notebook_id=notebook_id,
            context=context,
            on_progress=on_progress,
        )

    async def _embed(
        self,
        children: list[ChildChunk],
        context: str | None,
        on_progress: Callable[[int, int], None] | None,
    ) -> list[list[float]]:
        reuse = context is None and all(c.vector is not None for c in children)
        if reuse:
            return [list(c.vector or []) for c in children]
        inputs = [f"{context}\n\n{c.text}" if context else c.text for c in children]
        vectors: list[list[float]] = []
        for start in range(0, len(inputs), self.embed_batch_size):
            batch = inputs[start : start + self.embed_batch_size]
            vectors.extend(await asyncio.to_thread(self.embedder.embed, batch))
            if on_progress is not None:
                on_progress(len(vectors), len(inputs))
        if len(vectors) != len(children):
            raise ValueError(
                f"Embedding count mismatch: {len(vectors)} vectors for {len(children)} children"
            )
        return vectors

    async def _persist(
        self,
        session: AsyncSession,
        document_id: str,
        text: str,
        chunked: ChunkResult,
        *,
        strategy_name: str,
        strategy_version: str,
        params: dict[str, Any],
        notebook_id: str | None,
        context: str | None,
        on_progress: Callable[[int, int], None] | None,
    ) -> IngestResult:
        children = [c for p in chunked.parents for c in p.children]
        vectors = await self._embed(children, context, on_progress)
        features = await asyncio.to_thread(self._features, [c.text for c in children])
        lengths = [len(c.text) for c in children]

        run = ChunkRun(
            document_id=document_id,
            notebook_id=notebook_id,
            strategy=strategy_name,
            params={**params, **chunked.stats.extra, "embed_context": bool(context)},
            chunker_version=strategy_version,
            source_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            trace_id=current_trace_id(),
            n_parents=len(chunked.parents),
            n_children=len(children),
            mean_len=sum(lengths) / len(lengths),
            p95_len=_p95(lengths),
            entity_vetoes=chunked.stats.entity_vetoes,
            is_active=True,
        )
        session.add(run)
        await session.flush()
        # Read ids before commit: sessions with expire_on_commit would reload them.
        run_id = run.id
        await session.execute(
            update(ChunkRun)
            .where(ChunkRun.document_id == document_id, ChunkRun.id != run_id)
            .values(is_active=False)
        )

        external_ids: list[str] = []
        child_i = 0
        for p_index, parent in enumerate(chunked.parents):
            prow = ParentChunkRow(
                run_id=run_id,
                document_id=document_id,
                index=p_index,
                text=parent.text,
                char_start=parent.char_start,
                char_end=parent.char_end,
            )
            session.add(prow)
            await session.flush()
            for child in parent.children:
                external_id = f"{document_id}:{run_id}:{child_i}"
                feats = features[child_i]
                session.add(
                    Clause(
                        external_id=external_id,
                        text=child.text,
                        document_id=document_id,
                        run_id=run_id,
                        parent_id=prow.id,
                        sentence_index=child_i,
                        root_index=feats.root_index,
                        tokens=feats.tokens,
                        groups=feats.groups,
                    )
                )
                session.add(
                    Embedding(
                        clause_id=external_id,
                        embedding=vectors[child_i],
                        model=self.embedding_model_name,
                    )
                )
                external_ids.append(external_id)
                child_i += 1

        await session.commit()
        logger.info(
            "Ingested %d children / %d parents for %s (run %d, %s)",
            len(children),
            len(chunked.parents),
            document_id,
            run_id,
            strategy_name,
        )
        return IngestResult(run_id=run_id, external_ids=external_ids)
