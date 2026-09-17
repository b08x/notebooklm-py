from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from notebooklm._preprocessing.ingestion import IngestionService, resolve_notebook_context


def _make_client(content: str, summary: str = "") -> MagicMock:
    client = MagicMock()
    client.sources.get_fulltext = AsyncMock(return_value=SimpleNamespace(content=content))
    client.notebooks.get_summary = AsyncMock(return_value=summary)
    return client


def _make_session() -> MagicMock:
    session = MagicMock()
    session.add = MagicMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_ingest_source_writes_clauses_and_embeddings():
    client = _make_client("First sentence. Second sentence.")
    chunker = MagicMock()
    chunker.chunk.return_value = ["First sentence.", "Second sentence."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]

    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    count = await service.ingest_source(session, "nb-1", "src-1")

    assert count == 2
    assert session.add.call_count == 4  # 2 clauses + 2 embeddings
    session.commit.assert_awaited_once()

    added = [call.args[0] for call in session.add.call_args_list]
    clause_ids = {c.external_id for c in added if hasattr(c, "sentence_index")}
    assert clause_ids == {"src-1:0", "src-1:1"}


@pytest.mark.asyncio
async def test_ingest_source_empty_text_skips_embedding():
    client = _make_client("")
    chunker = MagicMock()
    chunker.chunk.return_value = []
    embedder = MagicMock()
    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    count = await service.ingest_source(session, "nb-1", "src-1")

    assert count == 0
    embedder.embed.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_ingest_source_vector_count_mismatch_raises():
    client = _make_client("One. Two.")
    chunker = MagicMock()
    chunker.chunk.return_value = ["One.", "Two."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]  # only one vector for two sentences
    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    with pytest.raises(ValueError, match="mismatch"):
        await service.ingest_source(session, "nb-1", "src-1")


@pytest.mark.asyncio
async def test_ingest_text_chunks_embeds_and_persists():
    client = MagicMock()
    chunker = MagicMock()
    chunker.chunk.return_value = ["First sentence.", "Second sentence."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    count = await service.ingest_text(
        session, document_id="artifact-1", text="irrelevant, chunker is mocked"
    )

    assert count == 2
    chunker.chunk.assert_called_once_with("irrelevant, chunker is mocked")
    client.sources.get_fulltext.assert_not_called()

    added = [call.args[0] for call in session.add.call_args_list]
    clause_ids = {c.external_id for c in added if hasattr(c, "sentence_index")}
    assert clause_ids == {"artifact-1:0", "artifact-1:1"}


@pytest.mark.asyncio
async def test_ingest_chunks_persists_caller_supplied_chunks_verbatim():
    client = MagicMock()
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder)
    count = await service.ingest_chunks(
        session, document_id="artifact-1", chunks=["Chunk one.", "Chunk two."]
    )

    assert count == 2
    embedder.embed.assert_called_once_with(["Chunk one.", "Chunk two."])


@pytest.mark.asyncio
async def test_ingest_chunks_deletes_existing_clauses_for_document_first():
    from sqlalchemy import Delete

    client = MagicMock()
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder)
    await service.ingest_chunks(session, document_id="artifact-1", chunks=["Only chunk."])

    session.execute.assert_awaited_once()
    executed_stmt = session.execute.call_args.args[0]
    assert isinstance(executed_stmt, Delete)


# ---------------------------------------------------------------------------
# contextual embedding (notebook-summary prefix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_notebook_context_returns_stripped_summary():
    client = MagicMock()
    client.notebooks.get_summary = AsyncMock(return_value="  This notebook covers Q3 earnings.  ")

    context = await resolve_notebook_context(client, "nb-1")

    assert context == "This notebook covers Q3 earnings."


@pytest.mark.asyncio
async def test_resolve_notebook_context_empty_summary_returns_none():
    client = MagicMock()
    client.notebooks.get_summary = AsyncMock(return_value="   ")

    assert await resolve_notebook_context(client, "nb-1") is None


@pytest.mark.asyncio
async def test_resolve_notebook_context_fetch_failure_returns_none():
    client = MagicMock()
    client.notebooks.get_summary = AsyncMock(side_effect=Exception("rpc down"))

    assert await resolve_notebook_context(client, "nb-1") is None


@pytest.mark.asyncio
async def test_ingest_source_prefixes_embedding_with_notebook_summary_by_default():
    client = _make_client("First sentence.", summary="Earnings call transcript.")
    chunker = MagicMock()
    chunker.chunk.return_value = ["First sentence."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    await service.ingest_source(session, "nb-1", "src-1")

    client.notebooks.get_summary.assert_awaited_once_with("nb-1")
    embedder.embed.assert_called_once_with(["Earnings call transcript.\n\nFirst sentence."])
    # The stored clause text stays unprefixed.
    added = [call.args[0] for call in session.add.call_args_list]
    clause = next(c for c in added if hasattr(c, "sentence_index"))
    assert clause.text == "First sentence."


@pytest.mark.asyncio
async def test_ingest_source_use_notebook_context_false_skips_fetch():
    client = _make_client("First sentence.", summary="Earnings call transcript.")
    chunker = MagicMock()
    chunker.chunk.return_value = ["First sentence."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    session = _make_session()

    service = IngestionService(
        client, embedder=embedder, chunker=chunker, use_notebook_context=False
    )
    await service.ingest_source(session, "nb-1", "src-1")

    client.notebooks.get_summary.assert_not_called()
    embedder.embed.assert_called_once_with(["First sentence."])


@pytest.mark.asyncio
async def test_ingest_source_explicit_context_overrides_auto_fetch():
    client = _make_client("First sentence.", summary="Auto summary, should be ignored.")
    chunker = MagicMock()
    chunker.chunk.return_value = ["First sentence."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    await service.ingest_source(session, "nb-1", "src-1", context="Custom context.")

    client.notebooks.get_summary.assert_not_called()
    embedder.embed.assert_called_once_with(["Custom context.\n\nFirst sentence."])


@pytest.mark.asyncio
async def test_ingest_source_explicit_empty_context_disables_prefix():
    client = _make_client("First sentence.", summary="Auto summary, should be ignored.")
    chunker = MagicMock()
    chunker.chunk.return_value = ["First sentence."]
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder, chunker=chunker)
    await service.ingest_source(session, "nb-1", "src-1", context="")

    client.notebooks.get_summary.assert_not_called()
    embedder.embed.assert_called_once_with(["First sentence."])


@pytest.mark.asyncio
async def test_ingest_chunks_applies_given_context_to_every_chunk():
    client = MagicMock()
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1, 0.2], [0.3, 0.4]]
    session = _make_session()

    service = IngestionService(client, embedder=embedder)
    await service.ingest_chunks(
        session,
        document_id="artifact-1",
        chunks=["Chunk one.", "Chunk two."],
        context="Podcast summary.",
    )

    embedder.embed.assert_called_once_with(
        ["Podcast summary.\n\nChunk one.", "Podcast summary.\n\nChunk two."]
    )


@pytest.mark.asyncio
async def test_ingest_chunks_sends_embedding_requests_in_batches():
    client = MagicMock()
    embedder = MagicMock()
    embedder.embed.side_effect = lambda batch: [[0.1] for _ in batch]
    session = _make_session()

    service = IngestionService(client, embedder=embedder, embed_batch_size=2)
    count = await service.ingest_chunks(
        session, document_id="artifact-1", chunks=["a", "b", "c", "d", "e"]
    )

    assert count == 5
    assert embedder.embed.call_count == 3
    assert [call.args[0] for call in embedder.embed.call_args_list] == [
        ["a", "b"],
        ["c", "d"],
        ["e"],
    ]


@pytest.mark.asyncio
async def test_ingest_chunks_reports_progress_per_batch():
    client = MagicMock()
    embedder = MagicMock()
    embedder.embed.side_effect = lambda batch: [[0.1] for _ in batch]
    session = _make_session()
    progress_calls: list[tuple[int, int]] = []

    service = IngestionService(client, embedder=embedder, embed_batch_size=2)
    await service.ingest_chunks(
        session,
        document_id="artifact-1",
        chunks=["a", "b", "c"],
        on_progress=lambda done, total: progress_calls.append((done, total)),
    )

    assert progress_calls == [(2, 3), (3, 3)]
