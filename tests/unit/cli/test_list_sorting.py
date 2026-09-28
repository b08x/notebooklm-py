import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from click.testing import CliRunner

from notebooklm.notebooklm_cli import cli
from tests.unit.cli.conftest import create_mock_client, inject_client


def test_cli_list_sort_flag_choices():
    runner = CliRunner()
    result = runner.invoke(cli, ["list", "--sort", "invalid"])
    assert result.exit_code != 0
    assert "Invalid value for '--sort'" in result.output


def test_cli_list_sort_by_name(mock_auth, mock_fetch_tokens):
    dt = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    mock_notebooks = [
        SimpleNamespace(
            id="nb-z",
            title="Zebra",
            is_owner=True,
            role=None,
            created_at=dt,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
        SimpleNamespace(
            id="nb-a",
            title="Apple",
            is_owner=True,
            role=None,
            created_at=dt,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
    ]

    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(return_value=mock_notebooks)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["list", "--sort", "name", "--json"], obj=inject_client(mock_client)
    )
    if result.exit_code != 0:
        print("TEST ERROR OUTPUT:", result.output, "EXCEPTION:", repr(result.exception))
    assert result.exit_code == 0
    assert "Apple" in result.output
    assert result.output.index("Apple") < result.output.index("Zebra")
