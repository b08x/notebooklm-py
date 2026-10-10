import asyncio
import concurrent.futures
import logging
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
    cache = getattr(state, "tui_cache", None)
    if cache is not None:
        cache.save_summary(notebook_id, summary)


def fetch_summary_if_needed(state: TUIState) -> None:
    if not state.selected_notebook:
        return

    # Check cache first
    cache = getattr(state, "tui_cache", None)
    if cache is not None:
        cached_summary = cache.get_summary(state.selected_notebook)
        if cached_summary:
            state.notebook_summaries[state.selected_notebook] = cached_summary
            return

    current = state.notebook_summaries.get(state.selected_notebook)
    if current and current not in (
        "Paused: Waiting for API capacity...",
        "Loading summary...",
    ):
        return

    if current == "Loading summary...":
        return

    # Don't try to fetch if we have no tokens
    if not state.consume_token():
        state.notebook_summaries[state.selected_notebook] = "Paused: Waiting for API capacity..."
        return

    # Store a placeholder so we don't fetch multiple times
    state.notebook_summaries[state.selected_notebook] = "Loading summary..."

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.summary_task = executor.submit(_run_summary, state, state.selected_notebook)


async def _fetch_notebook_stats_async(notebook_id: str, state: TUIState | None = None) -> dict:
    try:
        async with NotebookLMClient.from_storage() as client:
            sources = await client.sources.list(notebook_id)
            artifacts = await client.artifacts.list(notebook_id)
            stats: dict[str, Any] = {
                "source_count": len(sources),
                "artifact_count": len(artifacts),
                "artifact_types": [
                    a.kind.value if hasattr(a.kind, "value") else str(a.kind) for a in artifacts
                ],
            }
            if state:
                cache = getattr(state, "tui_cache", None)
                if cache is not None:
                    cached = cache.save_artifacts(notebook_id, artifacts)
                    stats.update(cached)
            return stats
    except Exception as e:
        return {"error": str(e)}


def _run_stats(state: TUIState, notebook_id: str) -> None:
    stats = asyncio.run(_fetch_notebook_stats_async(notebook_id, state))
    state.notebook_stats[notebook_id] = stats


def fetch_stats_if_needed(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    if state.selected_notebook in state.notebook_stats:
        return
    if state.notebook_stats.get(state.selected_notebook) == {"loading": True}:
        return

    # Check cache first
    cache = getattr(state, "tui_cache", None)
    if cache is not None:
        cached = cache.get_artifact_stats(state.selected_notebook)
        if cached:
            state.notebook_stats[state.selected_notebook] = cached
            return

    state.notebook_stats[state.selected_notebook] = {"loading": True}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.stats_task = executor.submit(_run_stats, state, state.selected_notebook)


def start_download(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    if state.job_store is None:
        state.error_message = "Job queue unavailable"
        return
    nb_id = state.selected_notebook
    state.job_store.enqueue("download", nb_id, {"download_dir": state.download_dir})
    title = next(
        (getattr(nb, "title", None) for nb in state.notebooks if getattr(nb, "id", None) == nb_id),
        None,
    )
    state.error_message = f"Queued download for {title or nb_id}"


async def _fetch_sources_async(notebook_id: str) -> tuple[list[Any], set[str]]:
    from sqlalchemy import select

    from notebooklm.db.models import Clause
    from notebooklm.db.session import async_session_maker

    async with NotebookLMClient.from_storage() as client:
        sources = await client.sources.list(notebook_id)
        try:
            # Notes are offered alongside sources (fact 19); mind maps are
            # excluded — they are JSON trees, not prose.
            notes = await client.notes.list(notebook_id)
        except Exception:
            notes = []

    items = [_IngestItem(src, "source") for src in sources] + [
        _IngestItem(note, "note") for note in notes
    ]
    item_ids = [item.id for item in items]
    ingested_ids = set()

    async with async_session_maker() as session:
        for did in item_ids:
            res = await session.execute(select(Clause.id).where(Clause.document_id == did).limit(1))
            if res.scalar_one_or_none() is not None:
                ingested_ids.add(did)

    return items, ingested_ids


class _IngestItem:
    """Picker-facing wrapper giving sources and notes one uniform shape."""

    def __init__(self, obj: Any, kind: str) -> None:
        self._obj = obj
        self.kind = kind

    @property
    def id(self) -> str:
        return self._obj.id

    @property
    def title(self) -> str:
        return getattr(self._obj, "title", None) or self._obj.id

    @property
    def content(self) -> str | None:
        return getattr(self._obj, "content", None)

    @property
    def source(self) -> Any:
        return self._obj

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return f"_IngestItem(kind={self.kind!r}, id={self.id!r})"


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


def start_ingestion(
    state: TUIState,
    selected_source_ids: set[str] | None = None,
    strategy: str = "recursive",
    params: dict[str, Any] | None = None,
) -> None:
    """Queue an ``ingest`` job for the selected notebook (see ``jobs/handlers/ingest.py``)."""
    if not state.selected_notebook:
        return
    if state.job_store is None:
        state.error_message = "Job queue unavailable"
        return
    state.job_store.enqueue(
        "ingest",
        state.selected_notebook,
        {
            "strategy": strategy,
            "params": params or {},
            "source_ids": sorted(selected_source_ids) if selected_source_ids is not None else None,
            "context": state.context_overrides.get(state.selected_notebook),
        },
    )
    state.jobs_snapshot_at = 0.0
    state.error_message = f"Queued ingest ({strategy}) for {state.selected_notebook}"


async def _assess_audio_overview_async(
    notebook_id: str,
    context_override: str | None = None,
    artifact_id: str | None = None,
    progress_cb=None,
    state=None,
) -> dict:
    from notebooklm._app.assessment import run_full_assessment, run_source_assessment
    from notebooklm.db.session import async_session_maker

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):

        def state_cb(key: str, value: Any):
            if progress_cb:
                progress_cb({"type": "state_update", "key": key, "value": value})

        def hitl_cb(chunk_text: str, sfl_context: str) -> bool:
            import time

            if state and getattr(state, "assessment_state", {}).get("auto_skip_meta", False):
                return True

            if progress_cb:
                progress_cb(
                    {
                        "type": "state_update",
                        "key": "hitl_prompt",
                        "value": {"chunk": chunk_text, "sfl": sfl_context, "decision": None},
                    }
                )

            # Spin wait for UI to set decision or auto_skip
            while state:
                if state.assessment_state.get("auto_skip_meta", False):
                    state.assessment_state["hitl_prompt"] = None
                    return True

                prompt_state = state.assessment_state.get("hitl_prompt")
                if prompt_state and prompt_state.get("decision") is None:
                    time.sleep(0.1)
                else:
                    decision = prompt_state.get("decision") if prompt_state else False
                    state.assessment_state["hitl_prompt"] = None
                    return decision
            return False

        if not artifact_id:
            if progress_cb:
                progress_cb("Fetching audio artifacts...")
            audio_artifacts = await client.artifacts.list_audio(notebook_id)
            if audio_artifacts:
                artifact = max(audio_artifacts, key=lambda a: getattr(a, "created_at", None) or 0)
                artifact_id = artifact.id
            else:
                # No audio — try source assessment path
                try:
                    result = await run_source_assessment(
                        client,
                        session,
                        notebook_id,
                        context_override=context_override,
                        progress_callback=progress_cb,
                        state_callback=state_cb,
                        hitl_callback=hitl_cb,
                    )
                    return {
                        "assessment_state": {
                            "artifact_id": None,
                            "assessment_mode": "sources",
                            "system_instructions": result.system_instructions,
                            "audio_metadata": result.audio_metadata,
                            "chunks": result.chunks,
                            "sfl_metrics": result.sfl_metrics,
                            "scroll_offset": 0,
                        }
                    }
                except ValueError:
                    return {
                        "error": "No assessable content found — generate an audio overview or ingest sources first."
                    }

        result = await run_full_assessment(
            client,
            session,
            notebook_id,
            artifact_id,
            context_override=context_override,
            progress_callback=progress_cb,
            state_callback=state_cb,
            hitl_callback=hitl_cb,
        )

        return {
            "assessment_state": {
                "artifact_id": artifact_id,
                "assessment_mode": "audio",
                "system_instructions": result.system_instructions,
                "audio_metadata": result.audio_metadata,
                "chunks": result.chunks,
                "sfl_metrics": result.sfl_metrics,
                "scroll_offset": 0,
            }
        }


def _run_assess_audio_overview(
    state: TUIState,
    notebook_id: str,
    context_override: str | None = None,
    artifact_id: str | None = None,
) -> None:
    def cb(msg: Any):
        if "assessment_state" not in state.__dict__:
            state.assessment_state = {}

        if isinstance(msg, dict) and msg.get("type") == "state_update":
            key = msg["key"]
            value = msg["value"]
            if key == "ticker_stream_append":
                if "ticker_stream" not in state.assessment_state:
                    state.assessment_state["ticker_stream"] = []
                state.assessment_state["ticker_stream"].append(value)
            else:
                state.assessment_state[key] = value
        else:
            state.assessment_state["loading_message"] = msg

    try:
        cb(f"Assessing audio overview for {notebook_id}...")
        outcome = asyncio.run(
            _assess_audio_overview_async(notebook_id, context_override, artifact_id, cb, state)
        )
        if "error" in outcome:
            state.error_message = outcome["error"]
            state.assessment_state["is_loading"] = False
            return
        state.error_message = None
        state.assessment_state = outcome["assessment_state"]
        if state.current_view != View.ASSESSMENT:
            state.previous_view = state.current_view
            state.current_view = View.ASSESSMENT

        # Automatically trigger fact-checking streaming in the background
        from notebooklm.tui.views.assessment_view import trigger_fact_check

        trigger_fact_check(state)
    except Exception as e:
        import logging

        err_msg = str(e)

        # Attempt to dig out response text from httpx or litellm errors
        cause: Any = e
        while cause:
            if hasattr(cause, "response") and hasattr(cause.response, "text"):
                err_msg += f"\nResponse Body: {cause.response.text}"
                break
            cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)

        logging.getLogger(__name__).exception(f"Assessment failed: {err_msg}")

        # Replace newlines with spaces for the single-line footer, but it will be in the log buffer fully
        footer_msg = err_msg.replace("\n", " | ")
        state.error_message = f"Assessment failed: {footer_msg}"
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
        _run_assess_audio_overview(
            state, notebook_id, state.context_overrides.get(notebook_id), None
        )
        return
    if len(artifacts) == 1:
        # Just run assessment immediately
        first_artifact = next(iter(artifacts))
        state.assessment_state = {
            "is_loading": True,
            "loading_message": "Transcribing and assessing audio overview...",
        }
        state.previous_view = state.current_view
        state.current_view = View.ASSESSMENT
        _run_assess_audio_overview(
            state, notebook_id, state.context_overrides.get(notebook_id), first_artifact.id
        )
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
