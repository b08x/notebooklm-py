import asyncio
import logging
from typing import Any

from notebooklm.client import NotebookLMClient

from ..state import TUIState

logger = logging.getLogger(__name__)


async def _fetch_notebooks() -> list[Any]:
    async with NotebookLMClient.from_storage() as client:
        return await client.notebooks.list()


def load_notebooks_sync(state: TUIState) -> None:
    cache = getattr(state, "tui_cache", None)
    try:
        notebooks = asyncio.run(_fetch_notebooks())
        state.notebooks = notebooks
        state.error_message = None
        if notebooks and not state.selected_notebook:
            state.selected_notebook = getattr(notebooks[0], "id", None)
        if cache is not None:
            cache.save_notebooks(notebooks)
    except Exception as e:
        logger.exception("Failed to load notebooks: %s", e)
        state.error_message = f"Failed to load notebooks: {e}"
        if not state.notebooks and cache is not None:
            cached = cache.get_notebooks()
            if cached:
                state.notebooks = cached
                if not state.selected_notebook:
                    state.selected_notebook = getattr(cached[0], "id", None)
