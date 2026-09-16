import click


@click.command()
def tui():
    """Launch the interactive Terminal User Interface (TUI)."""
    from notebooklm.tui import run_tui

    run_tui()


def register_tui_command(cli_group: click.Group) -> None:
    cli_group.add_command(tui)
