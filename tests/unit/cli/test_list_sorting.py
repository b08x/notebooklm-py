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


def test_cli_list_sort_by_created(mock_auth, mock_fetch_tokens):
    dt_old = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    dt_new = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    mock_notebooks = [
        SimpleNamespace(
            id="nb-old",
            title="Old Notebook",
            is_owner=True,
            role=None,
            created_at=dt_old,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
        SimpleNamespace(
            id="nb-new",
            title="New Notebook",
            is_owner=True,
            role=None,
            created_at=dt_new,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
    ]

    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(return_value=mock_notebooks)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["list", "--sort", "created", "--json"], obj=inject_client(mock_client)
    )
    assert result.exit_code == 0
    assert result.output.index("New Notebook") < result.output.index("Old Notebook")


def test_cli_list_sort_by_modified(mock_auth, mock_fetch_tokens):
    dt_base = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
    dt_mod_old = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    dt_mod_new = datetime.datetime(2026, 2, 1, tzinfo=datetime.timezone.utc)
    mock_notebooks = [
        SimpleNamespace(
            id="nb-1",
            title="Modified Earlier",
            is_owner=True,
            role=None,
            created_at=dt_base,
            modified_at=dt_mod_old,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
        SimpleNamespace(
            id="nb-2",
            title="Modified Later",
            is_owner=True,
            role=None,
            created_at=dt_base,
            modified_at=dt_mod_new,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
    ]

    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(return_value=mock_notebooks)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["list", "--sort", "modified", "--json"], obj=inject_client(mock_client)
    )
    assert result.exit_code == 0
    assert result.output.index("Modified Later") < result.output.index("Modified Earlier")


def test_cli_list_sort_by_artifacts(mock_auth, mock_fetch_tokens, monkeypatch):
    dt = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    mock_notebooks = [
        SimpleNamespace(
            id="nb-old-art",
            title="Older Artifacts",
            is_owner=True,
            role=None,
            created_at=dt,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
        SimpleNamespace(
            id="nb-new-art",
            title="Newer Artifacts",
            is_owner=True,
            role=None,
            created_at=dt,
            last_viewed_at=None,
            last_accessed_at=None,
        ),
    ]

    from notebooklm.tui.cache import TUICache

    fake_stats = {
        "nb-old-art": {"recent_generated_at": 1000.0},
        "nb-new-art": {"recent_generated_at": 2000.0},
    }
    monkeypatch.setattr(TUICache, "get_all_artifact_stats", lambda self: fake_stats)

    mock_client = create_mock_client()
    mock_client.notebooks.list = AsyncMock(return_value=mock_notebooks)

    runner = CliRunner()
    result = runner.invoke(
        cli, ["list", "--sort", "artifacts", "--json"], obj=inject_client(mock_client)
    )
    assert result.exit_code == 0
    assert result.output.index("Newer Artifacts") < result.output.index("Older Artifacts")
