"""Shared building blocks so every view uses the same panel, hint and scroll idiom."""

from rich import box
from rich.align import Align
from rich.console import Console, ConsoleOptions, RenderableType, RenderResult
from rich.panel import Panel
from rich.segment import Segment
from rich.text import Text


def key_hints(pairs: list[tuple[str, str]], sep: str = "   ") -> Text:
    """Render ``[(key, label), ...]`` as styled text without Rich markup.

    Building the Text directly avoids markup parsing, which silently drops
    lowercase bracketed keys such as ``[c]`` or ``[j/k]``.
    """
    text = Text(no_wrap=True, overflow="ellipsis")
    for i, (key, label) in enumerate(pairs):
        if i:
            text.append(sep)
        text.append(key, style="key")
        text.append(f" {label}", style="muted")
    return text


def panel(
    renderable: RenderableType,
    title: str | None = None,
    *,
    focused: bool = False,
    padding: tuple[int, int] = (0, 1),
) -> Panel:
    """Standard content panel: rounded box, left title, themed background."""
    return Panel(
        renderable,
        # A Text title skips markup parsing and renders at heading weight;
        # a str title would inherit the dim border color.
        title=Text(title, style="heading") if title else None,
        title_align="left",
        box=box.ROUNDED,
        border_style="border.focus" if focused else "border",
        style="main",
        padding=padding,
    )


def hint_panel(pairs: list[tuple[str, str]], title: str = "Keys") -> Panel:
    return panel(Align.center(key_hints(pairs, sep="  ·  "), vertical="middle"), title)


def message_panel(message: str, title: str, style: str = "muted") -> Panel:
    return panel(Align.center(Text(message, style=style), vertical="middle"), title)


def empty_panel(title: str | None = None) -> Panel:
    return panel(Text(""), title)


class TailView:
    """Render only the last lines that fit the available height.

    A Panel inside a Layout clips overflow at the bottom, which hides the
    newest chat messages and log lines. This keeps the tail visible instead.
    """

    def __init__(self, renderable: RenderableType) -> None:
        self.renderable = renderable

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        lines = console.render_lines(self.renderable, options.update(height=None), pad=False)
        if options.height is not None:
            lines = lines[-options.height :] if options.height > 0 else []
        new_line = Segment.line()
        for line in lines:
            yield from line
            yield new_line
