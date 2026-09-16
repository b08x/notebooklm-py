from rich.console import Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState


def render_chat(state: TUIState) -> Panel:
    from rich.console import RenderableType

    renderables: list[RenderableType] = []

    for msg in state.chat_history:
        if msg["role"] == "user":
            renderables.append(Text(f"You: {msg['text']}", style="prompt"))
        else:
            renderables.append(Markdown(msg["text"]))
        renderables.append(Text(""))  # padding

    if state.background_task and not state.background_task.done():
        renderables.append(Text("NotebookLM is typing...", style="muted italic"))

    renderables.append(Text("────────────────────────────────────────", style="border"))
    renderables.append(Text(f"> {state.chat_input}█", style="foreground"))

    return Panel(Group(*renderables), title="Chat", border_style="border", style="main")
