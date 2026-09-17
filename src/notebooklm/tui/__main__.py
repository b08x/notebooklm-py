import asyncio

import click


@click.group()
def tui_cli():
    """NotebookLM TUI Database Pipeline Frontend"""
    pass


@tui_cli.command()
@click.option(
    "--download-dir", type=click.Path(), default=None, help="Directory to download assets into"
)
def start(download_dir):
    """Start the TUI application."""
    from notebooklm.tui import run_tui

    run_tui(download_dir=download_dir)


@tui_cli.command()
@click.argument("notebook_id")
@click.argument("source_id")
def ingest(notebook_id: str, source_id: str):
    """Ingest a NotebookLM source's full text into the clauses/embeddings tables."""

    async def _run() -> None:
        from notebooklm import NotebookLMClient
        from notebooklm._preprocessing.ingestion import IngestionService
        from notebooklm.db.session import async_session_maker

        async with (
            NotebookLMClient.from_storage() as client,
            async_session_maker() as session,
        ):
            service = IngestionService(client)
            count = await service.ingest_source(session, notebook_id, source_id)
            click.echo(f"Ingested {count} clauses from source {source_id}")

    asyncio.run(_run())


def main():
    tui_cli()


if __name__ == "__main__":
    main()
