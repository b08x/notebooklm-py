import click


@click.group()
def tui_cli():
    """NotebookLM TUI Database Pipeline Frontend"""
    pass

@tui_cli.command()
def start():
    """Start the TUI application."""
    click.echo("Starting TUI...")

def main():
    tui_cli()

if __name__ == "__main__":
    main()
