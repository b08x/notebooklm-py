"""Schema assertions for the curation tables (removal_log, archived_notebooks)."""

from __future__ import annotations

from notebooklm.db.models import Base


def test_removal_log_table_and_columns() -> None:
    table = Base.metadata.tables["removal_log"]
    assert set(table.columns.keys()) == {
        "id",
        "created_at",
        "notebook_id",
        "notebook_title",
        "item_id",
        "item_title",
        "item_type",
        "action",
        "reason",
        "archive_path",
    }
    assert table.columns["archive_path"].nullable is True
    for col in (
        "notebook_id",
        "notebook_title",
        "item_id",
        "item_title",
        "item_type",
        "action",
        "reason",
    ):
        assert table.columns[col].nullable is False


def test_archived_notebooks_table_and_columns() -> None:
    table = Base.metadata.tables["archived_notebooks"]
    assert set(table.columns.keys()) == {
        "id",
        "created_at",
        "notebook_id",
        "title",
        "archive_path",
        "document_ids",
        "reason",
        "remote_deleted",
    }
    for col in ("notebook_id", "title", "archive_path", "document_ids", "reason", "remote_deleted"):
        assert table.columns[col].nullable is False


def test_curation_indexes_exist() -> None:
    removal = Base.metadata.tables["removal_log"]
    archived = Base.metadata.tables["archived_notebooks"]
    assert any(ix.columns.keys() == ["notebook_id"] for ix in removal.indexes)
    assert any(ix.columns.keys() == ["notebook_id"] for ix in archived.indexes)
