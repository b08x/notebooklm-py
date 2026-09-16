import asyncio
from typing import Any

from notebooklm.client import NotebookLMClient

from ..state import TUIState


async def _fetch_notebooks() -> list[Any]:
    async with NotebookLMClient.from_storage() as client:
        return await client.notebooks.list()


def load_notebooks_sync(state: TUIState) -> None:
    try:
        notebooks = asyncio.run(_fetch_notebooks())
        state.notebooks = notebooks
        state.error_message = None
        if notebooks and not state.selected_notebook:
            state.selected_notebook = getattr(notebooks[0], "id", None)
    except Exception as e:
        state.error_message = f"Failed to load notebooks: {e}"
        state.notebooks = []
