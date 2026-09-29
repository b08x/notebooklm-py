"""Background workers for curation actions (mark/remove/add/delete/archive).

Each action follows the existing ``_run_*`` / ``start_*`` pattern from
``tui/views/notebook_detail.py``: a ``ThreadPoolExecutor`` thread runs
``asyncio.run(...)`` with a fresh ``NotebookLMClient.from_storage()`` and an
``async_session_maker()`` session. Worker threads mutate ``state.curation``
in place, exactly like the ingestion and assessment workers do.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from pathlib import Path
from typing import Any

from notebooklm.client import NotebookLMClient
from notebooklm.db.session import async_session_maker

from ..state import TUIState, View

logger = logging.getLogger(__name__)


def _executor() -> concurrent.futures.ThreadPoolExecutor:
    return concurrent.futures.ThreadPoolExecutor(max_workers=1)


def _notebook_title(state: TUIState) -> str:
    nb = next((n for n in state.notebooks if n.id == state.selected_notebook), None)
    return getattr(nb, "title", "") or (state.selected_notebook or "")


def _forget_notebook(state: TUIState, notebook_id: str) -> None:
    """Drop a deleted notebook from the sidebar, stats, and cache."""
    state.notebooks = [nb for nb in state.notebooks if getattr(nb, "id", None) != notebook_id]
    state.notebook_stats.pop(notebook_id, None)
    state.notebook_summaries.pop(notebook_id, None)
    state.context_overrides.pop(notebook_id, None)
    cache = getattr(state, "tui_cache", None)
    if cache is not None:
        cache.forget(notebook_id)
    if state.current_view == View.NOTEBOOK_DETAIL:
        state.current_view = View.NOTEBOOK_LIST
        state.previous_view = None


# --- item list -----------------------------------------------------------------


async def _list_items_async(notebook_id: str) -> list[Any]:
    from notebooklm._app.curation import list_curation_items

    async with NotebookLMClient.from_storage() as client:
        return await list_curation_items(client, notebook_id)


def _run_curation_list(state: TUIState, notebook_id: str) -> None:
    curation = state.curation
    try:
        items = asyncio.run(_list_items_async(notebook_id))
    except Exception as e:
        logger.exception("Failed to list curation items for %s", notebook_id)
        if state.curation is not curation:
            state.error_message = f"Could not load items: {e}"
            return
        curation["loading"] = False
        curation["error"] = f"Could not load items: {e}"
        return
    if state.curation is not curation:
        return
    curation["items"] = items
    curation["loading"] = False


def start_curation_list(state: TUIState) -> None:
    """Open the item-marking modal and fetch its contents in the background."""
    if not state.selected_notebook:
        return
    state.curation = {
        "mode": "items",
        "notebook_id": state.selected_notebook,
        "notebook_title": _notebook_title(state),
        "items": [],
        "cursor": 0,
        "marked": set(),
        "loading": True,
        "error": None,
        "notice": None,
    }
    state.curation_task = _executor().submit(_run_curation_list, state, state.selected_notebook)


# --- remove items --------------------------------------------------------------


async def _remove_items_async(
    notebook_id: str, notebook_title: str, items: list[Any], reason: str
) -> Any:
    from notebooklm._app.curation import execute_remove_items

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        return await execute_remove_items(
            client, session, notebook_id, notebook_title, items, reason
        )


def _run_remove_items(state: TUIState, notebook_id: str, items: list[Any], reason: str) -> None:
    curation = state.curation
    notebook_title = curation.get("notebook_title", "")
    try:
        result = asyncio.run(_remove_items_async(notebook_id, notebook_title, items, reason))
    except Exception as e:
        logger.exception("Removal batch failed for %s", notebook_id)
        if state.curation is not curation:
            state.error_message = f"Removal failed: {e}"
            return
        curation["busy"] = False
        curation["error"] = f"Removal failed: {e}"
        return

    notice = f"Removed {len(result.removed)} item(s) ({reason})."
    if result.failed:
        failed_titles = ", ".join(item.title for item, _ in result.failed)
        notice += f" Failed: {failed_titles}."

    if state.curation is not curation:
        state.error_message = notice
        return

    # Refresh the list so the removed items disappear and the failed ones
    # stay listed (fact 5).
    try:
        curation["items"] = asyncio.run(_list_items_async(notebook_id))
    except Exception:
        curation["items"] = [
            item for item in curation.get("items", []) if item not in result.removed
        ]
    curation["marked"] = set()
    curation["cursor"] = 0
    curation["busy"] = False
    curation["error"] = None
    curation["notice"] = notice


def start_remove_items(state: TUIState, items: list[Any], reason: str) -> None:
    curation = state.curation
    notebook_id = curation.get("notebook_id")
    if not notebook_id or not items:
        return
    curation["busy"] = True
    curation["notice"] = f"Removing {len(items)} item(s)..."
    state.curation_task = _executor().submit(_run_remove_items, state, notebook_id, items, reason)


# --- add source ----------------------------------------------------------------


async def _add_source_async(notebook_id: str, kind: str, value: str) -> Any:
    from notebooklm._app.curation import execute_add_source

    async with NotebookLMClient.from_storage() as client:
        return await execute_add_source(client, notebook_id, kind, value)


def _run_add_source(state: TUIState, notebook_id: str, kind: str, value: str) -> None:
    curation = state.curation
    try:
        source = asyncio.run(_add_source_async(notebook_id, kind, value))
        title = getattr(source, "title", None) or "new source"
        message = f"Added source: {title}"
        ok = True
    except Exception as e:
        logger.exception("Add source failed for %s", notebook_id)
        message = f"Add source failed: {e}"
        ok = False

    # Refresh the live stats so the new source shows up without a restart
    # (fact 6). _fetch_notebook_stats_async re-saves the artifact cache.
    from .notebook_detail import _fetch_notebook_stats_async

    try:
        state.notebook_stats[notebook_id] = asyncio.run(
            _fetch_notebook_stats_async(notebook_id, state)
        )
    except Exception:
        state.notebook_stats.pop(notebook_id, None)

    if state.curation is not curation:
        state.error_message = message
        return
    curation["busy"] = False
    if ok:
        state.curation = {}
        state.error_message = message
    else:
        curation["error"] = message


def start_add_source(state: TUIState, kind: str, value: str) -> None:
    curation = state.curation
    notebook_id = curation.get("notebook_id")
    if not notebook_id:
        return
    curation["busy"] = True
    curation["error"] = None
    state.curation_task = _executor().submit(_run_add_source, state, notebook_id, kind, value)


# --- notebook delete -----------------------------------------------------------


async def _delete_notebook_async(notebook_id: str, notebook_title: str, reason: str) -> None:
    from notebooklm._app.curation import execute_delete_notebook

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        await execute_delete_notebook(client, session, notebook_id, notebook_title, reason)


def _run_notebook_delete(
    state: TUIState, notebook_id: str, notebook_title: str, reason: str
) -> None:
    try:
        asyncio.run(_delete_notebook_async(notebook_id, notebook_title, reason))
    except Exception as e:
        logger.exception("Notebook delete failed for %s", notebook_id)
        state.error_message = f"Delete failed: {e}"
        return
    _forget_notebook(state, notebook_id)
    state.error_message = f"Deleted notebook: {notebook_title} ({reason})"


def start_notebook_delete(state: TUIState, reason: str) -> None:
    curation = state.curation
    notebook_id = curation.get("notebook_id")
    if not notebook_id:
        return
    notebook_title = curation.get("notebook_title", "")
    state.curation = {}
    state.curation_task = _executor().submit(
        _run_notebook_delete, state, notebook_id, notebook_title, reason
    )


# --- archive -------------------------------------------------------------------


async def _archive_async(notebook_id: str, reason: str, progress_cb: Any) -> Any:
    from notebooklm._app.archive import run_archive

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        return await run_archive(client, session, notebook_id, reason, progress_cb)


def _archive_summary(result: Any) -> str:
    if result.error:
        return f"Archive failed: {result.error}"
    if result.final_path is None:
        failed = ", ".join(item.get("title", item.get("id", "?")) for item in result.failed_items)
        return f"Archive incomplete (kept at {result.partial_path.name}); failed items: {failed}"
    verify = result.verify
    size_kb = (verify.total_bytes or 0) / 1024
    return (
        f"Archive verified: {verify.file_count} files, {size_kb:.1f} KB — "
        f"{result.final_path.name}. Type the notebook title to delete the remote notebook."
    )


def _run_archive(state: TUIState, notebook_id: str, reason: str) -> None:
    curation = state.curation

    def progress_cb(done: int, total: int) -> None:
        curation["archive"] = {"done": done, "total": total}

    from notebooklm._app.archive import ArchiveResult

    try:
        result = asyncio.run(_archive_async(notebook_id, reason, progress_cb))
    except Exception as e:
        logger.exception("Archive failed for %s", notebook_id)
        result = ArchiveResult(
            notebook_id=notebook_id,
            notebook_title=curation.get("notebook_title", ""),
            reason=reason,
            partial_path=Path(str(notebook_id)),
            error=str(e),
        )

    if state.curation is not curation:
        state.error_message = _archive_summary(result)
        return

    curation["busy"] = False
    curation["archive_result"] = result
    curation["error"] = None
    if result.error is None and result.final_path is not None:
        # Verification passed: ask for the typed-title confirmation before the
        # remote delete (fact 13).
        curation["mode"] = "typed_confirm"
        curation["pending"] = "archive_delete"
        curation["buffer"] = ""
        curation["notice"] = _archive_summary(result)
    else:
        curation["mode"] = "archive_result"
        curation["notice"] = _archive_summary(result)


def start_archive(state: TUIState, reason: str) -> None:
    curation = state.curation
    notebook_id = curation.get("notebook_id")
    if not notebook_id:
        return
    curation["mode"] = "archive_progress"
    curation["busy"] = True
    curation["error"] = None
    curation["notice"] = None
    curation["archive"] = {"done": 0, "total": 0}
    state.curation_task = _executor().submit(_run_archive, state, notebook_id, reason)


async def _archive_delete_async(archive_result: Any, typed_title: str) -> bool:
    from notebooklm._app.archive import execute_archive_delete

    async with (
        NotebookLMClient.from_storage() as client,
        async_session_maker() as session,
    ):
        return await execute_archive_delete(client, session, archive_result, typed_title)


def _run_archive_delete(state: TUIState, archive_result: Any, typed_title: str) -> None:
    try:
        deleted = asyncio.run(_archive_delete_async(archive_result, typed_title))
    except Exception as e:
        logger.exception("Archive remote delete failed for %s", archive_result.notebook_id)
        state.error_message = f"Remote delete failed: {e}"
        return
    if not deleted:
        state.error_message = "Title did not match — the remote notebook was kept."
        return
    _forget_notebook(state, archive_result.notebook_id)
    state.error_message = f"Notebook deleted remotely; archive kept at {archive_result.final_path}"


def start_archive_delete(state: TUIState, typed_title: str) -> None:
    curation = state.curation
    archive_result = curation.get("archive_result")
    state.curation = {}
    if archive_result is None:
        return
    state.curation_task = _executor().submit(
        _run_archive_delete, state, archive_result, typed_title
    )


# --- modal openers for keys bound outside the item list -------------------------


def start_add_source_modal(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.curation = {
        "mode": "add_kind",
        "notebook_id": state.selected_notebook,
        "notebook_title": _notebook_title(state),
        "error": None,
    }


def start_notebook_delete_modal(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.curation = {
        "mode": "reason",
        "pending": "delete_notebook",
        "notebook_id": state.selected_notebook,
        "notebook_title": _notebook_title(state),
        "items": [],
        "error": None,
    }


def start_archive_modal(state: TUIState) -> None:
    if not state.selected_notebook:
        return
    state.curation = {
        "mode": "reason",
        "pending": "archive",
        "notebook_id": state.selected_notebook,
        "notebook_title": _notebook_title(state),
        "items": [],
        "error": None,
    }
