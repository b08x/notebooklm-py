import asyncio
import concurrent.futures
from pathlib import Path

from notebooklm.client import NotebookLMClient

from ..state import TUIState


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
