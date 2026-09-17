import asyncio
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._preprocessing.chunkers import StructuralCoherenceChunker
from notebooklm._preprocessing.embeddings import EmbeddingAdapter, OllamaEmbeddingAdapter
from notebooklm.db.models import Clause, Embedding

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


class IngestionService:
    """Ingests text into the clauses/embeddings tables.

    :meth:`ingest_source` fetches full text from the NotebookLM API
    (`client.sources.get_fulltext`); :meth:`ingest_text` chunks, embeds, and
    persists any already-resolved text (e.g. an audio overview transcript)
    under a caller-supplied ``document_id``.

    Chunks are embedded with the source's summary prepended as context
    (``resolve_source_context``), unless ``use_source_context=False`` or a
    caller passes its own ``context`` override (e.g. a user-edited summary from
    the TUI, or ``""`` to force no context). The prefix is embedding-input only
    — ``Clause.text`` always stores the unprefixed chunk.
    """

    def __init__(
        self,
        client: Any,
        embedder: EmbeddingAdapter | None = None,
        chunker: Any | None = None,
        embedding_model_name: str = "embeddinggemma-300m",
        use_source_context: bool = True,
        embed_batch_size: int = 32,
    ):
        self.client = client
        self.embedder = embedder or OllamaEmbeddingAdapter()
        self.chunker = chunker or StructuralCoherenceChunker()
        self.embedding_model_name = embedding_model_name
        self.use_source_context = use_source_context
        #: A single ``/api/embed`` request holds all its texts in memory for the
        #: whole request/response round trip; capping the batch size bounds how
        #: long any one request can legitimately take, so a slow/remote Ollama
        #: host degrades to a slower ingest rather than a single-request timeout
        #: partway through a large document.
        self.embed_batch_size = embed_batch_size

    async def _resolve_context(self, notebook_id: str, source_id: str, explicit_context: str | None) -> str | None:
        if explicit_context is not None:
            return explicit_context.strip() or None
        if not self.use_source_context:
            return None
        return await resolve_source_context(self.client, notebook_id, source_id)

    async def ingest_source(
        self,
        session: AsyncSession,
        notebook_id: str,
        source_id: str,
        *,
        context: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Chunk, embed, and persist one source's text. Returns clauses written."""
        import os

        from sqlalchemy import select

        from notebooklm.db.models import LocalAsset

        # Check local cache first
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
            context=resolved_context,
            on_progress=on_progress,
        )

    async def ingest_text(
        self,
        session: AsyncSession,
        document_id: str,
        text: str,
        *,
        context: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Chunk, embed, and persist already-resolved text. Returns clauses written."""
        sentences = [s for s in self.chunker.chunk(text) if s.strip()]
        return await self.ingest_chunks(
            session, document_id, sentences, context=context, on_progress=on_progress
        )

    async def ingest_chunks(
        self,
        session: AsyncSession,
        document_id: str,
        chunks: list[str],
        *,
        context: str | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> int:
        """Embed and persist already-chunked text. Returns clauses written.

        Callers that need clause rows keyed 1:1 to chunks they already produced
        (e.g. the assessment pipeline's structured chunks) call this directly
        instead of ``ingest_text``, whose own chunker would otherwise produce a
        different split than the caller's.

        Re-ingesting the same ``document_id`` (e.g. re-running an assessment)
        deletes that document's existing clauses first, since ``Clause.external_id``
        (``f"{document_id}:{index}"``) is unique and would otherwise collide.

        ``context``, when given, is prepended to each chunk's embedding input
        only (not stored as clause text) — this method does not auto-fetch it
        since it has no ``notebook_id``; use :func:`resolve_notebook_context` or
        ``ingest_source``/``ingest_text``, which do.

        Embedding requests are sent in batches of ``self.embed_batch_size`` (not
        all chunks in one request) to bound how long any single request can
        take. ``on_progress(embedded_count, total_count)``, when given, is
        called after each batch — callers driving a UI progress indicator wire
        it to update finer than "started"/"done" for a single large document.
        """
        sentences = [s for s in chunks if s.strip()]
        if not sentences:
            logger.info("Document %s produced no clauses to ingest", document_id)
            return 0

        embed_inputs = [f"{context}\n\n{s}" for s in sentences] if context else sentences
        vectors: list[list[float]] = []
        for start in range(0, len(embed_inputs), self.embed_batch_size):
            batch = embed_inputs[start : start + self.embed_batch_size]
            batch_vectors = await asyncio.to_thread(self.embedder.embed, batch)
            vectors.extend(batch_vectors)
            if on_progress is not None:
                on_progress(len(vectors), len(embed_inputs))
        if len(vectors) != len(sentences):
            raise ValueError(
                f"Embedding count mismatch: {len(vectors)} vectors for {len(sentences)} sentences"
            )

        await session.execute(delete(Clause).where(Clause.document_id == document_id))

        for index, (sentence, vector) in enumerate(zip(sentences, vectors, strict=True)):
            external_id = f"{document_id}:{index}"
            session.add(
                Clause(
                    external_id=external_id,
                    text=sentence,
                    document_id=document_id,
                    sentence_index=index,
                )
            )
            session.add(
                Embedding(
                    clause_id=external_id,
                    embedding=vector,
                    model=self.embedding_model_name,
                )
            )

        await session.commit()
        logger.info("Ingested %d clauses for document %s", len(sentences), document_id)
        return len(sentences)
