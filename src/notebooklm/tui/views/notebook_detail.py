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

    current = state.notebook_summaries.get(state.selected_notebook)
    if current and current not in (
        "Paused: Waiting for API capacity...",
        "Loading summary...",
        "Waiting for scroll...",
    ):
        return

    if current == "Loading summary...":
        return

    import time

    if time.time() - state.last_selection_time < 0.5:
        # User is still scrolling. We'll set a visual indicator.
        state.notebook_summaries[state.selected_notebook] = "Waiting for scroll..."
        return

    # Don't try to fetch if we have no tokens
    if not state.consume_token():
        state.notebook_summaries[state.selected_notebook] = "Paused: Waiting for API capacity..."
        return

    # Store a placeholder so we don't fetch multiple times
    state.notebook_summaries[state.selected_notebook] = "Loading summary..."

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.summary_task = executor.submit(_run_summary, state, state.selected_notebook)


async def _fetch_notebook_stats_async(notebook_id: str) -> dict:
    try:
        async with NotebookLMClient.from_storage() as client:
            sources = await client.sources.list(notebook_id)
            artifacts = await client.artifacts.list(notebook_id)
            return {
                "source_count": len(sources),
                "artifact_count": len(artifacts),
                "artifact_types": [a.kind.value if hasattr(a.kind, "value") else str(a.kind) for a in artifacts],
            }
    except Exception as e:
        return {"error": str(e)}


def _run_stats(state: TUIState, notebook_id: str) -> None:
    stats = asyncio.run(_fetch_notebook_stats_async(notebook_id))
    state.notebook_stats[notebook_id] = stats


def fetch_stats_if_needed(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    if state.selected_notebook in state.notebook_stats:
        return
    if state.notebook_stats.get(state.selected_notebook) == {"loading": True}:
        return

    state.notebook_stats[state.selected_notebook] = {"loading": True}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.stats_task = executor.submit(_run_stats, state, state.selected_notebook)


async def _download_assets_async(state: TUIState, notebook_id: str) -> str:
    from sqlalchemy import select

    from notebooklm.db.models import LocalAsset
    from notebooklm.db.session import async_session_maker

    async def _upsert_asset(session, asset_id: str, asset_type: str, local_path: str):
        result = await session.execute(select(LocalAsset).where(LocalAsset.asset_id == asset_id))
        asset = result.scalar_one_or_none()
        if asset:
            asset.local_path = local_path
        else:
            asset = LocalAsset(
                notebook_id=notebook_id,
                asset_id=asset_id,
                asset_type=asset_type,
                local_path=local_path
            )
            session.add(asset)
        await session.commit()

    try:
        async with NotebookLMClient.from_storage() as client:
            nb = await client.notebooks.get(notebook_id)
            title = getattr(nb, "title", "Unknown Notebook") or "Unknown Notebook"
            title_safe = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()

            if state.download_dir:
                out_dir = Path(state.download_dir) / f"{title_safe}_assets"
            else:
                out_dir = Path.cwd() / f"{title_safe}_assets"
            out_dir.mkdir(parents=True, exist_ok=True)

            state.download_progress = {"phase": "Listing sources...", "percent": 0.0, "done": False}

            # 1. Download Sources
            sources_dir = out_dir / "sources"
            sources_dir.mkdir(exist_ok=True)
            sources = await client.sources.list(notebook_id)

            async with async_session_maker() as session:
                async def _is_asset_downloaded(session, asset_id: str) -> bool:
                    import os
                    result = await session.execute(select(LocalAsset).where(LocalAsset.asset_id == asset_id))
                    asset = result.scalar_one_or_none()
                    return bool(asset and os.path.exists(asset.local_path))

                for i, src in enumerate(sources):
                    state.download_progress = {
                        "phase": f"Downloading source {i+1}/{len(sources)}",
                        "percent": (i / len(sources)) * 0.33,
                        "done": False
                    }
                    try:
                        if await _is_asset_downloaded(session, src.id):
                            continue

                        await asyncio.sleep(0.5)  # conscious rate limiting
                        ft = await client.sources.get_fulltext(
                            notebook_id, src.id, output_format="markdown"
                        )
                        if ft.content:
                            src_title_str = getattr(src, "title", "Unknown Source") or "Unknown Source"
                            src_title = "".join(
                                c for c in src_title_str if c.isalnum() or c in (" ", "-", "_")
                            ).strip()
                            file_path = sources_dir / f"{src_title}.md"
                            file_path.write_text(ft.content)
                            await _upsert_asset(session, src.id, "source", str(file_path.absolute()))
                    except Exception:
                        pass

                # 2. Download Chat History
                state.download_progress = {"phase": "Downloading chat history...", "percent": 0.33, "done": False}
                try:
                    await asyncio.sleep(0.5)
                    history = await client.chat.get_history(notebook_id)
                    chat_text = ""
                    for turn in history:
                        chat_text += f"**User**: {turn[0]}\n\n**AI**: {turn[1]}\n\n"
                    if chat_text:
                        (out_dir / "chat_history.md").write_text(chat_text)
                except Exception:
                    pass

                # 3. Download Artifacts
                artifacts_dir = out_dir / "artifacts"
                artifacts_dir.mkdir(exist_ok=True)

                state.download_progress = {"phase": "Listing artifacts...", "percent": 0.66, "done": False}
                try:
                    all_artifacts = await client.artifacts.list(notebook_id)
                    for i, artifact in enumerate(all_artifacts):
                        state.download_progress = {
                            "phase": f"Downloading artifact {i+1}/{len(all_artifacts)}",
                            "percent": 0.66 + ((i / len(all_artifacts)) * 0.33),
                            "done": False
                        }

                        try:
                            if await _is_asset_downloaded(session, artifact.id):
                                continue

                            await asyncio.sleep(0.5)  # conscious rate limiting
                            safe_title = "".join(
                                c for c in artifact.title if c.isalnum() or c in (" ", "-", "_")
                            ).strip()
                            if not safe_title:
                                safe_title = artifact.id

                            raw_kind = artifact.kind.value if hasattr(artifact.kind, "value") else str(artifact.kind)
                            kind = str(raw_kind).lower()
                            file_path = None

                            if kind == "audio":
                                file_path = artifacts_dir / f"{safe_title}.wav"
                                await client.artifacts.download_audio(notebook_id, str(file_path), artifact.id)
                            elif kind == "video":
                                file_path = artifacts_dir / f"{safe_title}.mp4"
                                await client.artifacts.download_video(notebook_id, str(file_path), artifact.id)
                            elif kind == "report":
                                file_path = artifacts_dir / f"{safe_title}.md"
                                await client.artifacts.download_report(notebook_id, str(file_path), artifact.id)
                            elif kind == "quiz":
                                file_path = artifacts_dir / f"{safe_title}.md"
                                await client.artifacts.download_quiz(notebook_id, str(file_path), artifact.id)
                            elif kind == "flashcards":
                                file_path = artifacts_dir / f"{safe_title}.md"
                                await client.artifacts.download_flashcards(notebook_id, str(file_path), artifact.id)
                            elif kind == "infographic":
                                file_path = artifacts_dir / f"{safe_title}.png"
                                await client.artifacts.download_infographic(notebook_id, str(file_path), artifact.id)
                            elif kind == "slide_deck":
                                file_path = artifacts_dir / f"{safe_title}.pdf"
                                await client.artifacts.download_slide_deck(notebook_id, str(file_path), artifact.id)
                            elif kind == "data_table":
                                file_path = artifacts_dir / f"{safe_title}.csv"
                                await client.artifacts.download_data_table(notebook_id, str(file_path), artifact.id)
                            elif kind == "mind_map":
                                file_path = artifacts_dir / f"{safe_title}.md"
                                await client.artifacts.download_mind_map(notebook_id, str(file_path), artifact.id)

                            if file_path and file_path.exists():
                                await _upsert_asset(session, artifact.id, "artifact", str(file_path.absolute()))
                        except Exception as e:
                            logger.warning(f"Failed to download artifact {artifact.id}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to list artifacts for {notebook_id}: {e}")

            state.download_progress = {"phase": f"Assets downloaded to {out_dir}", "percent": 1.0, "done": True}
            return f"Assets downloaded to {out_dir}"
    except Exception as e:
        state.download_progress = {"phase": f"Download failed: {e}", "percent": 0.0, "done": True}
        return f"Download failed: {e}"


def _run_download(state: TUIState, notebook_id: str) -> None:
    try:
        result = asyncio.run(_download_assets_async(state, notebook_id))
        state.error_message = result
    except Exception as e:
        logger.exception("Download task crashed")
        state.error_message = f"Download crashed: {e}"


def start_download(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.error_message = f"Starting download for {state.selected_notebook}..."
    state.download_progress = {"phase": "Starting download...", "percent": 0.0, "done": False}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.background_task = executor.submit(_run_download, state, state.selected_notebook)


async def _fetch_sources_async(notebook_id: str) -> tuple[list[Any], set[str]]:
    from sqlalchemy import select

    from notebooklm.db.models import Clause
    from notebooklm.db.session import async_session_maker

    async with NotebookLMClient.from_storage() as client:
        sources = await client.sources.list(notebook_id)

    source_ids = [s.id for s in sources]
    ingested_ids = set()

    async with async_session_maker() as session:
        for sid in source_ids:
            res = await session.execute(select(Clause.id).where(Clause.document_id == sid).limit(1))
            if res.scalar_one_or_none() is not None:
                ingested_ids.add(sid)

    return sources, ingested_ids


def _run_fetch_sources(state: TUIState, notebook_id: str) -> None:
    try:
        sources, ingested_ids = asyncio.run(_fetch_sources_async(notebook_id))
    except Exception as e:
        logger.exception("Failed to list sources for %s", notebook_id)
        state.error_message = f"Could not load sources: {e}"
        return
    state.ingest_sources = sources
    state.ingest_completed = ingested_ids
    state.ingest_selected = {s.id for s in sources if s.id not in ingested_ids}
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
    notebook_id: str, context_override: str | None = None, artifact_id: str | None = None
) -> dict:
    from notebooklm._app.assessment import run_full_assessment
    from notebooklm.db.session import async_session_maker

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        if not artifact_id:
            audio_artifacts = await client.artifacts.list_audio(notebook_id)
            if not audio_artifacts:
                return {"error": f"No generated audio overview found for {notebook_id}."}
            artifact = max(audio_artifacts, key=lambda a: getattr(a, "created_at", None) or 0)
            artifact_id = artifact.id

        result = await run_full_assessment(
            client, session, notebook_id, artifact_id, context_override=context_override
        )
        return {
            "assessment_state": {
                "artifact_id": artifact_id,
                "system_instructions": result.system_instructions,
                "audio_metadata": result.audio_metadata,
                "chunks": result.chunks,
                "sfl_metrics": result.sfl_metrics,
                "scroll_offset": 0,
            }
        }


def _run_assess_audio_overview(
    state: TUIState, notebook_id: str, context_override: str | None = None, artifact_id: str | None = None
) -> None:
    try:
        state.error_message = f"Assessing audio overview for {notebook_id}..."
        outcome = asyncio.run(_assess_audio_overview_async(notebook_id, context_override, artifact_id))
        if "error" in outcome:
            state.error_message = outcome["error"]
            state.assessment_state["is_loading"] = False
            return
        state.error_message = None
        state.assessment_state = outcome["assessment_state"]
        if state.current_view != View.ASSESSMENT:
            state.previous_view = state.current_view
            state.current_view = View.ASSESSMENT
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Assessment failed")
        state.error_message = f"Assessment failed: {e}"
        state.assessment_state["is_loading"] = False


async def _fetch_audio_artifacts_async(notebook_id: str) -> list[Any]:
    async with NotebookLMClient.from_storage() as client:
        return await client.artifacts.list_audio(notebook_id)


def _run_fetch_audio_artifacts(state: TUIState, notebook_id: str) -> None:
    try:
        artifacts = asyncio.run(_fetch_audio_artifacts_async(notebook_id))
    except Exception as e:
        logger.exception("Failed to list artifacts for %s", notebook_id)
        state.error_message = f"Could not load artifacts: {e}"
        return
    if not artifacts:
        state.error_message = f"No generated audio overview found for {notebook_id}."
        return
    if len(artifacts) == 1:
        # Just run assessment immediately
        state.assessment_state = {
            "is_loading": True,
            "loading_message": "Transcribing and assessing audio overview...",
        }
        state.previous_view = state.current_view
        state.current_view = View.ASSESSMENT
        _run_assess_audio_overview(state, notebook_id, state.context_overrides.get(notebook_id), artifacts[0].id)
    else:
        state.audio_artifacts = artifacts
        state.artifact_cursor = 0
        state.selecting_artifact = True
        state.error_message = None


def start_assess_audio_overview(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.error_message = f"Fetching audio overviews for {state.selected_notebook}..."
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.background_task = executor.submit(
        _run_fetch_audio_artifacts, state, state.selected_notebook
    )
