import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import Any

from notebooklm.client import NotebookLMClient

from ..state import TUIState, View

logger = logging.getLogger(__name__)


async def _fetch_summary_async(notebook_id: str) -> str:
    try:
        async with NotebookLMClient.from_storage() as client:
            return await client.notebooks.get_summary(notebook_id)
    except Exception as e:
        return f"Error loading summary: {e}"


def _run_summary(state: TUIState, notebook_id: str) -> None:
    # This runs in a background thread
    summary = asyncio.run(_fetch_summary_async(notebook_id))
    state.notebook_summaries[notebook_id] = summary


def fetch_summary_if_needed(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    if state.selected_notebook in state.notebook_summaries:
        return

    # Store a placeholder so we don't fetch multiple times
    state.notebook_summaries[state.selected_notebook] = "Loading summary..."

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.summary_task = executor.submit(_run_summary, state, state.selected_notebook)


async def _download_assets_async(notebook_id: str) -> str:
    try:
        async with NotebookLMClient.from_storage() as client:
            nb = await client.notebooks.get(notebook_id)
            title = getattr(nb, "title", "Unknown Notebook") or "Unknown Notebook"
            title_safe = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
            out_dir = Path.cwd() / f"{title_safe}_assets"
            out_dir.mkdir(parents=True, exist_ok=True)

            # 1. Download Sources
            sources_dir = out_dir / "sources"
            sources_dir.mkdir(exist_ok=True)
            sources = await client.sources.list(notebook_id)
            for src in sources:
                try:
                    ft = await client.sources.get_fulltext(
                        notebook_id, src.id, output_format="markdown"
                    )
                    if ft.content:
                        src_title_str = getattr(src, "title", "Unknown Source") or "Unknown Source"
                        src_title = "".join(
                            c for c in src_title_str if c.isalnum() or c in (" ", "-", "_")
                        ).strip()
                        (sources_dir / f"{src_title}.md").write_text(ft.content)
                except Exception:
                    pass

            # 2. Download Chat History
            try:
                history = await client.chat.get_history(notebook_id)
                chat_text = ""
                for turn in history:
                    chat_text += f"**User**: {turn[0]}\n\n**AI**: {turn[1]}\n\n"
                if chat_text:
                    (out_dir / "chat_history.md").write_text(chat_text)
            except Exception:
                pass

            return f"Assets downloaded to {out_dir}"
    except Exception as e:
        return f"Download failed: {e}"


def _run_download(state: TUIState, notebook_id: str) -> None:
    result = asyncio.run(_download_assets_async(notebook_id))
    state.error_message = result


def start_download(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.error_message = f"Starting download for {state.selected_notebook}..."
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.background_task = executor.submit(_run_download, state, state.selected_notebook)


async def _fetch_sources_async(notebook_id: str) -> list[Any]:
    async with NotebookLMClient.from_storage() as client:
        return await client.sources.list(notebook_id)


def _run_fetch_sources(state: TUIState, notebook_id: str) -> None:
    try:
        sources = asyncio.run(_fetch_sources_async(notebook_id))
    except Exception as e:
        logger.exception("Failed to list sources for %s", notebook_id)
        state.error_message = f"Could not load sources: {e}"
        return
    state.ingest_sources = sources
    state.ingest_selected = {s.id for s in sources}
    state.ingest_cursor = 0
    state.selecting_sources = True


def start_source_selection(state: TUIState) -> None:
    """Fetch this notebook's sources in the background, then open the picker.

    The picker (``state.selecting_sources``) opens once ``state.ingest_sources``
    is populated; see ``_run_fetch_sources``. All sources are pre-selected by
    default, matching the previous "ingest everything" behavior.
    """
    if not state.selected_notebook:
        return
    state.error_message = f"Loading sources for {state.selected_notebook}..."
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.source_fetch_task = executor.submit(_run_fetch_sources, state, state.selected_notebook)


async def _ingest_notebook_async(
    notebook_id: str,
    context_override: str | None = None,
    selected_source_ids: set[str] | None = None,
    progress: dict[str, Any] | None = None,
) -> str:
    from notebooklm._preprocessing.ingestion import IngestionService
    from notebooklm.db.session import async_session_maker

    if progress is None:
        progress = {}

    try:
        async with (
            NotebookLMClient.from_storage() as client,
            async_session_maker() as session,
        ):
            sources = await client.sources.list(notebook_id)
            if selected_source_ids is not None:
                sources = [s for s in sources if s.id in selected_source_ids]

            service = IngestionService(client)
            progress["total_sources"] = len(sources)
            progress["done_sources"] = 0
            progress["failures"] = []
            total_clauses = 0
            failures = 0
            first_error: Exception | None = None
            for src in sources:
                title = getattr(src, "title", None) or src.id
                progress["current_title"] = title
                progress["current_chunks_done"] = 0
                progress["current_chunks_total"] = 0

                def _on_progress(done: int, total: int) -> None:
                    progress["current_chunks_done"] = done
                    progress["current_chunks_total"] = total

                try:
                    total_clauses += await service.ingest_source(
                        session,
                        notebook_id,
                        src.id,
                        context=context_override,
                        on_progress=_on_progress,
                    )
                except Exception as e:
                    logger.exception("Ingestion failed for source %s", src.id)
                    failures += 1
                    progress["failures"].append((title, str(e)))
                    if first_error is None:
                        first_error = e
                progress["done_sources"] += 1

            summary = f"Ingested {total_clauses} clauses from {len(sources)} sources."
            if failures:
                summary += f" ({failures} source(s) failed: {first_error})"
            return summary
    except Exception as e:
        return f"Ingestion failed: {e}"


def _run_ingestion(
    state: TUIState,
    notebook_id: str,
    context_override: str | None = None,
    selected_source_ids: set[str] | None = None,
    progress: dict[str, Any] | None = None,
) -> None:
    result = asyncio.run(
        _ingest_notebook_async(notebook_id, context_override, selected_source_ids, progress)
    )
    state.error_message = result


def start_ingestion(state: TUIState, selected_source_ids: set[str] | None = None) -> None:
    if not state.selected_notebook:
        return
    state.error_message = f"Starting ingestion for {state.selected_notebook}..."
    state.ingest_progress = {}
    context_override = state.context_overrides.get(state.selected_notebook)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.background_task = executor.submit(
        _run_ingestion,
        state,
        state.selected_notebook,
        context_override,
        selected_source_ids,
        state.ingest_progress,
    )


async def _assess_audio_overview_async(
    notebook_id: str, context_override: str | None = None
) -> dict:
    from notebooklm._app.assessment import run_full_assessment
    from notebooklm.db.session import async_session_maker

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        audio_artifacts = await client.artifacts.list_audio(notebook_id)
        if not audio_artifacts:
            return {"error": f"No generated audio overview found for {notebook_id}."}

        artifact = max(audio_artifacts, key=lambda a: getattr(a, "created_at", None) or 0)
        result = await run_full_assessment(
            client, session, notebook_id, artifact.id, context_override=context_override
        )
        return {
            "assessment_state": {
                "system_instructions": result.system_instructions,
                "audio_metadata": result.audio_metadata,
                "chunks": result.chunks,
                "scroll_offset": 0,
            }
        }


def _run_assess_audio_overview(
    state: TUIState, notebook_id: str, context_override: str | None = None
) -> None:
    outcome = asyncio.run(_assess_audio_overview_async(notebook_id, context_override))
    if "error" in outcome:
        state.error_message = outcome["error"]
        return
    state.assessment_state = outcome["assessment_state"]
    state.current_view = View.ASSESSMENT


def start_assess_audio_overview(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.error_message = f"Assessing audio overview for {state.selected_notebook}..."
    context_override = state.context_overrides.get(state.selected_notebook)
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.background_task = executor.submit(
        _run_assess_audio_overview, state, state.selected_notebook, context_override
    )
