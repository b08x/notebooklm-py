import asyncio
import concurrent.futures

from notebooklm.client import NotebookLMClient

from ..state import TUIState


async def _send_chat_async(notebook_id: str, text: str) -> str:
    try:
        async with NotebookLMClient.from_storage() as client:
            response = await client.chat.ask(notebook_id, text)
            return response.answer
    except Exception as e:
        return f"Error: {e}"


def _run_chat(state: TUIState, notebook_id: str, text: str) -> None:
    # This runs in a background thread
    response = asyncio.run(_send_chat_async(notebook_id, text))
    state.chat_history.append({"role": "bot", "text": response})


def submit_chat_message(state: TUIState) -> None:
    text = state.chat_input.strip()
    if not text or not state.selected_notebook:
        return

    state.chat_history.append({"role": "user", "text": text})
    state.chat_input = ""

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    state.background_task = executor.submit(_run_chat, state, state.selected_notebook, text)
