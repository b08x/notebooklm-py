"""Unit tests for the curation business-logic layer (``notebooklm._app.curation``)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from notebooklm._app.curation import (
    REMOVAL_REASONS,
    CurationItem,
    execute_add_source,
    execute_delete_notebook,
    execute_remove_items,
    list_curation_items,
    title_confirmation_matches,
    validate_add_source,
)


class FakeSession:
    """In-memory stand-in for an AsyncSession that records added rows."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.committed = 0

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed += 1


def _fake_client(**method_mocks: Any) -> SimpleNamespace:
    def _mock(name: str, **kwargs: Any) -> AsyncMock:
        return method_mocks.get(name, AsyncMock(**kwargs))

    return SimpleNamespace(
        sources=SimpleNamespace(
            list=_mock("sources_list", return_value=[]),
            delete=_mock("sources_delete"),
            add_url=_mock("sources_add_url"),
            add_file=_mock("sources_add_file"),
            add_text=_mock("sources_add_text"),
        ),
        artifacts=SimpleNamespace(
            list=_mock("artifacts_list", return_value=[]),
            delete=_mock("artifacts_delete"),
        ),
        notes=SimpleNamespace(
            list=_mock("notes_list", return_value=[]),
            delete=_mock("notes_delete"),
            delete_mind_map=_mock("notes_delete_mind_map"),
        ),
        mind_maps=SimpleNamespace(
            list_note_backed=_mock("mind_maps_list_note_backed", return_value=[]),
        ),
        notebooks=SimpleNamespace(
            delete=_mock("notebooks_delete"),
        ),
    )


# --- list_curation_items ------------------------------------------------------


@pytest.mark.asyncio
async def test_list_curation_items_returns_every_kind() -> None:
    client = _fake_client(
        sources_list=AsyncMock(
            return_value=[SimpleNamespace(id="src-1", title="A source", url="https://x.test")]
        ),
        artifacts_list=AsyncMock(return_value=[SimpleNamespace(id="art-1", title="A report")]),
        notes_list=AsyncMock(return_value=[SimpleNamespace(id="note-1", title="A note")]),
        mind_maps_list_note_backed=AsyncMock(
            return_value=[SimpleNamespace(id="mm-1", title="A mind map")]
        ),
    )

    items = await list_curation_items(client, "nb-1")

    assert [(i.kind, i.id) for i in items] == [
        ("source", "src-1"),
        ("artifact", "art-1"),
        ("note", "note-1"),
        ("mind_map", "mm-1"),
    ]


@pytest.mark.asyncio
async def test_list_curation_items_survives_mind_map_rpc_failure() -> None:
    client = _fake_client()
    client.mind_maps.list_note_backed = AsyncMock(side_effect=RuntimeError("boom"))

    items = await list_curation_items(client, "nb-1")

    assert items == []


# --- execute_remove_items -----------------------------------------------------


@pytest.mark.asyncio
async def test_remove_items_requires_a_known_reason_before_any_network_call() -> None:
    client = _fake_client()
    session = FakeSession()

    with pytest.raises(ValueError, match="reason"):
        await execute_remove_items(
            client,
            session,
            "nb-1",
            "Notebook",
            [CurationItem("source", "src-1", "S")],
            "because I said so",
        )

    client.sources.delete.assert_not_awaited()
    assert session.added == []


@pytest.mark.asyncio
async def test_remove_items_partial_failure_logs_only_successes() -> None:
    client = _fake_client()
    client.sources.delete = AsyncMock(side_effect=[None, RuntimeError("quota exceeded")])
    session = FakeSession()
    items = [CurationItem("source", "src-1", "Keep me"), CurationItem("source", "src-2", "Broken")]

    result = await execute_remove_items(client, session, "nb-1", "Notebook", items, "redundant")

    assert [item.id for item in result.removed] == ["src-1"]
    assert len(result.failed) == 1
    assert result.failed[0][0].id == "src-2"
    assert "quota exceeded" in result.failed[0][1]
    assert len(session.added) == 1
    row = session.added[0]
    assert row.item_id == "src-1"
    assert row.action == "remove"
    assert row.reason == "redundant"
    assert session.committed == 1


@pytest.mark.asyncio
async def test_remove_items_does_not_commit_when_nothing_was_removed() -> None:
    client = _fake_client()
    client.sources.delete = AsyncMock(side_effect=RuntimeError("down"))
    session = FakeSession()

    result = await execute_remove_items(
        client,
        session,
        "nb-1",
        "Notebook",
        [CurationItem("source", "src-1", "S")],
        "incorrect",
    )

    assert result.removed == []
    assert len(result.failed) == 1
    assert session.added == []
    assert session.committed == 0


@pytest.mark.parametrize(
    ("kind", "api_name", "method"),
    [
        ("source", "sources", "delete"),
        ("artifact", "artifacts", "delete"),
        ("note", "notes", "delete"),
        ("mind_map", "notes", "delete_mind_map"),
    ],
)
@pytest.mark.asyncio
async def test_remove_items_dispatches_each_kind_to_the_right_delete(
    kind: str, api_name: str, method: str
) -> None:
    client = _fake_client()
    session = FakeSession()

    result = await execute_remove_items(
        client,
        session,
        "nb-1",
        "Notebook",
        [CurationItem(kind, "item-1", "Item")],
        "experimental",
    )

    getattr(getattr(client, api_name), method).assert_awaited_once_with("nb-1", "item-1")
    assert result.removed[0].kind == kind
    assert session.added[0].item_type == kind


@pytest.mark.asyncio
async def test_remove_items_rejects_unknown_kind_as_failure() -> None:
    client = _fake_client()
    session = FakeSession()

    result = await execute_remove_items(
        client,
        session,
        "nb-1",
        "Notebook",
        [CurationItem("playlist", "item-1", "Item")],
        "other",
    )

    assert result.removed == []
    assert "Unknown item kind" in result.failed[0][1]


# --- validate_add_source ------------------------------------------------------


def test_validate_add_source_accepts_http_urls() -> None:
    assert validate_add_source("url", "https://example.com/page") == "https://example.com/page"


def test_validate_add_source_rejects_non_http_and_empty_urls() -> None:
    assert validate_add_source("url", "ftp://example.com") is None
    assert validate_add_source("url", "example.com") is None
    assert validate_add_source("url", "") is None
    assert validate_add_source("url", "   ") is None


def test_validate_add_source_requires_existing_regular_file(tmp_path) -> None:
    existing = tmp_path / "doc.pdf"
    existing.write_text("data")
    assert validate_add_source("file", str(existing)) == str(existing)
    assert validate_add_source("file", str(tmp_path / "missing.pdf")) is None
    assert validate_add_source("file", str(tmp_path)) is None  # a directory is not a regular file


def test_validate_add_source_requires_non_empty_text() -> None:
    assert validate_add_source("text", "some pasted text") == "some pasted text"
    assert validate_add_source("text", "") is None
    assert validate_add_source("text", "   ") is None


def test_validate_add_source_rejects_unknown_kind() -> None:
    assert validate_add_source("carrier-pigeon", "x") is None


# --- execute_add_source -------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_add_source_routes_url_through_add_url() -> None:
    client = _fake_client()

    await execute_add_source(client, "nb-1", "url", "https://www.youtube.com/watch?v=abc")

    client.sources.add_url.assert_awaited_once_with("nb-1", "https://www.youtube.com/watch?v=abc")


@pytest.mark.asyncio
async def test_execute_add_source_routes_file_through_add_file() -> None:
    client = _fake_client()

    await execute_add_source(client, "nb-1", "file", "/tmp/report.pdf")

    client.sources.add_file.assert_awaited_once_with("nb-1", "/tmp/report.pdf")


@pytest.mark.asyncio
async def test_execute_add_source_routes_text_through_add_text_with_default_title() -> None:
    client = _fake_client()

    await execute_add_source(client, "nb-1", "text", "pasted content")

    client.sources.add_text.assert_awaited_once_with("nb-1", "Pasted text", "pasted content")


@pytest.mark.asyncio
async def test_execute_add_source_rejects_unknown_kind() -> None:
    client = _fake_client()

    with pytest.raises(ValueError, match="Unknown add-source kind"):
        await execute_add_source(client, "nb-1", "telepathy", "x")


# --- title confirmation -------------------------------------------------------


def test_title_confirmation_accepts_prefixes_case_insensitively() -> None:
    assert title_confirmation_matches("Curation Smoke", "curation") is True
    assert title_confirmation_matches("Curation Smoke", "CURATION SMOKE") is True
    assert title_confirmation_matches("Curation Smoke", "curation smoke") is True


def test_title_confirmation_rejects_short_and_wrong_prefixes() -> None:
    assert title_confirmation_matches("Curation Smoke", "cur") is False  # below 4-char minimum
    assert title_confirmation_matches("Curation Smoke", "smoke") is False  # not a prefix
    assert title_confirmation_matches("Curation Smoke", "") is False
    assert title_confirmation_matches("Curation Smoke", "   ") is False
    assert title_confirmation_matches("Curation Smoke", "Curation Smoke Extra") is False


def test_title_confirmation_allows_full_title_for_short_titles() -> None:
    assert title_confirmation_matches("Ab", "Ab") is True  # min(len(title), 4) == 2


# --- execute_delete_notebook ---------------------------------------------------


@pytest.mark.asyncio
async def test_execute_delete_notebook_deletes_and_logs() -> None:
    client = _fake_client()
    session = FakeSession()

    await execute_delete_notebook(client, session, "nb-1", "Notebook", "hallucinated")

    client.notebooks.delete.assert_awaited_once_with("nb-1")
    row = session.added[0]
    assert row.item_type == "notebook"
    assert row.action == "delete_notebook"
    assert row.reason == "hallucinated"
    assert session.committed == 1


@pytest.mark.asyncio
async def test_execute_delete_notebook_requires_known_reason() -> None:
    client = _fake_client()
    session = FakeSession()

    with pytest.raises(ValueError, match="reason"):
        await execute_delete_notebook(client, session, "nb-1", "Notebook", "spite")

    client.notebooks.delete.assert_not_awaited()


def test_removal_reasons_are_the_fixed_five() -> None:
    assert REMOVAL_REASONS == ("redundant", "incorrect", "experimental", "hallucinated", "other")
