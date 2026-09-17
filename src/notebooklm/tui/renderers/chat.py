from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState


def render_chat(state: TUIState) -> tuple[Panel, Panel]:
    from rich.console import RenderableType

    history_renderables: list[RenderableType] = []

    for msg in state.chat_history:
        if msg["role"] == "user":
            history_renderables.append(Text(f"You: {msg['text']}", style="prompt"))
        else:
            history_renderables.append(Markdown(msg["text"]))
        history_renderables.append(Text(""))  # padding

    history_panel = Panel(
        Group(*history_renderables), title="Chat History", border_style="border", style="main"
    )

    input_renderables: list[RenderableType] = []
    if state.background_task and not state.background_task.done():
        input_renderables.append(Text("NotebookLM is typing...", style="muted italic"))

    input_renderables.append(Text(f"> {state.chat_input}█", style="foreground"))
    input_panel = Panel(
        Group(*input_renderables), title="Message", border_style="border", style="main"
    )

    return history_panel, input_panel
