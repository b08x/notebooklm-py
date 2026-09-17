import click


@click.command()
@click.option("--download-dir", type=click.Path(), default=None, help="Directory to download assets into")
def tui(download_dir):
    """Launch the interactive Terminal User Interface (TUI)."""
    from notebooklm.tui import run_tui

    run_tui(download_dir=download_dir)


def register_tui_command(cli_group: click.Group) -> None:
    cli_group.add_command(tui)

