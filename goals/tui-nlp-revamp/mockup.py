from rich.align import Align
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


def make_mockup():
    layout = Layout(name="root")

    # Split root into header, body, footer
    layout.split_column(
        Layout(name="header", size=3), Layout(name="body"), Layout(name="footer", size=3)
    )

    # 3-Pane Body Split
    layout["body"].split_row(Layout(name="sidebar", ratio=1), Layout(name="content", ratio=3))

    # Split content into results list and detail view
    layout["content"].split_column(Layout(name="results", ratio=1), Layout(name="detail", ratio=1))

    # Header
    layout["header"].update(
        Panel(
            Align.center(Text("NotebookLM TUI - NLP Revamp Mockup", style="bold white on blue")),
            style="blue",
        )
    )

    # Sidebar (Tree)
    tree = Tree("📚 [b]Notebooks[/b]")
    nb1 = tree.add("▶ [green]Machine Learning Concepts[/green]")
    nb1.add("📄 Source: Attention is all you need.pdf")
    nb1.add("📄 Source: LLM architectures.txt")
    nb2 = tree.add("  [white]Python Tutorials[/white]")
    nb2.add("📄 Source: rich-docs.md")

    tree.add("")
    commands = tree.add("⚙️  [b]Commands[/b]")
    commands.add("[Enter] Select")
    commands.add("[c] Chat")
    commands.add("[p] Compiler")
    commands.add("[q] Quit")

    layout["sidebar"].update(Panel(tree, title="Corpus & Actions", border_style="green"))

    # Results List (Table)
    table = Table(expand=True, show_edge=False, box=None)
    table.add_column("Score", justify="right", style="cyan", width=6)
    table.add_column("Snippet")
    table.add_column("Source", justify="right", style="magenta")

    table.add_row(
        "0.98",
        "The transformer architecture relies entirely on an attention mechanism...",
        "Attention.pdf",
    )
    table.add_row(
        "0.85",
        "Multi-head attention allows the model to jointly attend to information...",
        "Attention.pdf",
    )
    table.add_row(
        "0.72",
        "Decoder-only architectures have become the standard for modern LLMs...",
        "LLM arch.txt",
    )

    layout["results"].update(Panel(table, title="Search Results / History", border_style="cyan"))

    # Detail View
    detail_text = Text()
    detail_text.append("Document: Attention is all you need.pdf\n\n", style="bold white")
    detail_text.append(
        "Context: The attention mechanism is described as a mapping of a query and a set of key-value pairs to an output. ",
        style="white",
    )
    detail_text.append(
        "In this architecture, self-attention computes the representation of the sequence by relating different positions.",
        style="italic grey74",
    )

    layout["detail"].update(
        Panel(detail_text, title="Detail View (Markdown / Syntax)", border_style="yellow")
    )

    # Footer
    layout["footer"].update(
        Panel(
            "Input: /search attention mechanism in transformers█",
            title="Input Bar",
            border_style="white",
        )
    )

    return layout


if __name__ == "__main__":
    console = Console()
    console.print(make_mockup())
