from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from ..state import TUIState
from ._widgets import TailView, key_hints, panel


def render_chat(state: TUIState) -> tuple[Panel, Panel]:
    history_renderables: list[RenderableType] = []

    for msg in state.chat_history:
        if msg["role"] == "user":
            history_renderables.append(Text("You", style="prompt"))
            history_renderables.append(Padding(Text(msg["text"], style="foreground"), (0, 0, 1, 2)))
        else:
            history_renderables.append(Text("NotebookLM", style="heading"))
            history_renderables.append(Padding(Markdown(msg["text"]), (0, 0, 1, 2)))

    if not history_renderables:
        history_renderables.append(Text("Ask a question about this notebook.", style="muted"))

    # TailView keeps the newest exchange visible once history outgrows the pane.
    history_panel = panel(TailView(Group(*history_renderables)), "Chat", padding=(1, 2))

    input_renderables: list[RenderableType] = []
    if state.background_task and not state.background_task.done():
        input_renderables.append(Text("NotebookLM is answering…", style="muted italic"))

    line = Text()
    line.append("› ", style="prompt")
    line.append(state.chat_input, style="foreground")
    line.append("▏", style="prompt")
    input_renderables.append(line)
    input_renderables.append(Text(""))
    input_renderables.append(key_hints([("enter", "send"), ("esc", "back")]))
    input_panel = panel(Group(*input_renderables), "Message", focused=True, padding=(1, 2))

    return history_panel, input_panel
