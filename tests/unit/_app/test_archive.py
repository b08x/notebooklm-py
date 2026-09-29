"""Unit tests for the archive-then-delete business logic (``notebooklm._app.archive``)."""

from __future__ import annotations

import datetime
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Select

from notebooklm._app import archive as archive_module
from notebooklm._app.archive import (
    STATUS_FAILED,
    STATUS_NOT_DOWNLOADABLE,
    STATUS_OK,
    ArchiveResult,
    archive_filename,
    archive_root,
    execute_archive_delete,
    finalize_archive,
    record_archive,
    run_archive,
    slugify,
    verify_archive,
    write_tarball,
)
from notebooklm.db.models import ArchivedNotebook, RemovalLog


class FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> list[Any]:
        return self._rows


class FakeDbSession:
    """Session double: filters ``select(Model).where(col.in_(ids))`` in memory."""

    def __init__(self, clauses: list[Any] = (), embeddings: list[Any] = ()) -> None:
        self._clauses = list(clauses)
        self._embeddings = list(embeddings)
        self.added: list[Any] = []
        self.deleted: list[Any] = []
        self.executed: list[Any] = []
        self.committed = 0
        self._next_id = 1

    def add(self, obj: Any) -> None:
        if getattr(obj, "id", None) is None and isinstance(obj, ArchivedNotebook):
            obj.id = self._next_id
            self._next_id += 1
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def get(self, model: type, pk: Any) -> Any:
        for row in self.added:
            if isinstance(row, model) and row.id == pk:
                return row
        return None

    async def execute(self, stmt: Any) -> FakeResult:
        self.executed.append(stmt)
        entity = stmt.column_descriptions[0]["entity"]
        ids = set(stmt.whereclause.right.effective_value)
        if entity.__name__ == "Clause":
            return FakeResult([row for row in self._clauses if row.document_id in ids])
        return FakeResult([row for row in self._embeddings if row.clause_id in ids])

    async def commit(self) -> None:
        self.committed += 1


def _source(sid: str, title: str, *, url: str | None = None) -> Any:
    return SimpleNamespace(id=sid, title=title, url=url, download_url=None, created_at=None)


def _artifact(
    aid: str, title: str, *, kind: str = "report", completed: bool = True, prompt: str | None = None
) -> Any:
    return SimpleNamespace(
        id=aid,
        title=title,
        kind=SimpleNamespace(value=kind),
        status_str="completed" if completed else "in_progress",
        status=6 if completed else 3,
        generation_prompt=prompt,
        is_completed=lambda: completed,
        created_at=None,
    )


def _note(nid: str, title: str, content: str = "note body") -> Any:
    return SimpleNamespace(id=nid, title=title, content=content, created_at=None)


class FakeClient:
    """Client double whose download methods write bytes like the real ones."""

    def __init__(
        self,
        sources: list[Any] = (),
        artifacts: list[Any] = (),
        notes: list[Any] = (),
        mind_maps: list[Any] = (),
        history: list[tuple[str, str]] = (),
        failing_artifact_ids: set[str] = frozenset(),
        failing_source_ids: set[str] = frozenset(),
    ) -> None:
        self.sources = SimpleNamespace(
            list=AsyncMock(return_value=list(sources)),
            get_fulltext=AsyncMock(side_effect=self._get_fulltext),
        )
        self.artifacts = SimpleNamespace(
            list=AsyncMock(return_value=list(artifacts)),
            download_report=AsyncMock(side_effect=self._download),
            download_audio=AsyncMock(side_effect=self._download),
            download_video=AsyncMock(side_effect=self._download),
            download_quiz=AsyncMock(side_effect=self._download),
            download_flashcards=AsyncMock(side_effect=self._download),
            download_infographic=AsyncMock(side_effect=self._download),
            download_slide_deck=AsyncMock(side_effect=self._download),
            download_data_table=AsyncMock(side_effect=self._download),
            download_mind_map=AsyncMock(side_effect=self._download),
        )
        self.notes = SimpleNamespace(list=AsyncMock(return_value=list(notes)))
        self.mind_maps = SimpleNamespace(list_note_backed=AsyncMock(return_value=list(mind_maps)))
        self.chat = SimpleNamespace(get_history=AsyncMock(return_value=list(history)))
        self.notebooks = SimpleNamespace(
            get=AsyncMock(return_value=SimpleNamespace(id="nb-1", title="Test Notebook")),
            delete=AsyncMock(),
        )
        self._failing_artifact_ids = set(failing_artifact_ids)
        self._failing_source_ids = set(failing_source_ids)

    async def _get_fulltext(self, notebook_id: str, source_id: str, **_: Any) -> Any:
        if source_id in self._failing_source_ids:
            raise RuntimeError("fulltext fetch exploded")
        return SimpleNamespace(content=f"# {source_id}\n\nFull text of {source_id}.")

    async def _download(self, notebook_id: str, output_path: str, artifact_id: str) -> None:
        if artifact_id in self._failing_artifact_ids:
            raise RuntimeError("download exploded")
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"artifact-bytes-{artifact_id}".encode())


@pytest.fixture(autouse=True)
def _fast_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(archive_module, "DOWNLOAD_SPACING_SECONDS", 0.0)


@pytest.fixture(autouse=True)
def _archive_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "archive"
    monkeypatch.setenv("NOTEBOOKLM_ARCHIVE_DIR", str(root))
    return root


# --- naming -------------------------------------------------------------------


def test_archive_filename_format() -> None:
    name = archive_filename("My Curation Notebook!", "abcdef123456", datetime.date(2026, 9, 29))
    assert name == "my-curation-notebook_abcdef12_20260929.tar.gz"


def test_archive_root_creates_missing_directory(_archive_dir: Path) -> None:
    root = archive_root()
    assert root == _archive_dir
    assert root.is_dir()


def test_slugify_collapses_and_lowercases() -> None:
    assert slugify("  Curation: Smoke, Notebook!! ") == "curation-smoke-notebook"
    assert slugify("") == "untitled"


# --- full staged run -----------------------------------------------------------


@pytest.mark.asyncio
async def test_run_archive_collects_every_item_type_and_finalizes() -> None:
    client = FakeClient(
        sources=[
            _source("src-web", "Web source", url="https://example.com/page"),
            _source("src-upload", "Uploaded file"),
        ],
        artifacts=[_artifact("art-1", "Report", kind="report", prompt="Explain the sources")],
        notes=[_note("note-1", "Meeting note")],
        mind_maps=[
            SimpleNamespace(id="mm-1", title="Mind map", tree={"name": "root"}, created_at=None)
        ],
        history=[("question?", "answer.")],
    )
    session = FakeDbSession(
        clauses=[
            SimpleNamespace(
                id=1,
                external_id="c1",
                document_id="src-web",
                text="clause one",
                sentence_index=0,
                root_index=0,
            ),
            SimpleNamespace(
                id=2,
                external_id="c2",
                document_id="other-nb-doc",
                text="clause from another notebook",
                sentence_index=0,
                root_index=0,
            ),
        ],
        embeddings=[
            SimpleNamespace(id=1, clause_id="c1", model="test-model", embedding=[0.1, 0.2]),
            SimpleNamespace(id=2, clause_id="c2", model="test-model", embedding=[0.3]),
        ],
    )
    progress: list[tuple[int, int]] = []

    result = await run_archive(
        client, session, "nb-1", "redundant", lambda d, t: progress.append((d, t))
    )

    assert result.error is None
    assert result.final_path is not None and result.final_path.is_file()
    assert not result.partial_path.exists()

    manifest = result.manifest
    assert manifest is not None
    types = {item["type"] for item in manifest["items"]}
    assert types == {
        "source",
        "source_original",
        "artifact",
        "note",
        "mind_map",
        "chat",
        "db_export",
    }
    artifact_entry = next(item for item in manifest["items"] if item["type"] == "artifact")
    assert artifact_entry["status"] == STATUS_OK
    assert artifact_entry["generation_prompt"] == "Explain the sources"
    original_entry = next(item for item in manifest["items"] if item["type"] == "source_original")
    assert original_entry["status"] == STATUS_NOT_DOWNLOADABLE
    web_entry = next(item for item in manifest["items"] if item["id"] == "src-web")
    assert web_entry["url"] == "https://example.com/page"
    # Uploaded originals do not block the finalize (only `failed` does).
    assert all(item["status"] != STATUS_FAILED for item in manifest["items"])

    with tarfile.open(result.final_path, "r:gz") as tar:
        names = {member.name for member in tar.getmembers()}
        manifest_json = tar.extractfile("manifest.json")
        assert manifest_json is not None
        assert json.loads(manifest_json.read())
    for item in manifest["items"]:
        if item["status"] == STATUS_OK and item["archive_path"]:
            assert item["archive_path"] in names, item

    # Progress covered every item.
    assert progress and progress[-1][0] == progress[-1][1]

    # The DB export contains only this notebook's document ids.
    db_entry = next(item for item in manifest["items"] if item["type"] == "db_export")
    with tarfile.open(result.final_path, "r:gz") as tar:
        clauses_file = tar.extractfile("db/clauses.jsonl")
        assert clauses_file is not None
        clause_rows = [json.loads(line) for line in clauses_file.read().splitlines()]
    assert [row["document_id"] for row in clause_rows] == ["src-web"]
    assert db_entry["archive_path"] == "db/clauses.jsonl"

    # The archived-notebook record and removal log row were written.
    archived_rows = [row for row in session.added if isinstance(row, ArchivedNotebook)]
    assert len(archived_rows) == 1
    assert archived_rows[0].notebook_id == "nb-1"
    assert archived_rows[0].document_ids == ["art-1", "note-1", "src-upload", "src-web"]
    assert archived_rows[0].remote_deleted is False
    assert result.archive_record_id == archived_rows[0].id
    log_rows = [row for row in session.added if isinstance(row, RemovalLog)]
    assert len(log_rows) == 1
    assert log_rows[0].action == "archive"
    assert log_rows[0].archive_path == str(result.final_path)

    # The staging directory is cleaned up.
    assert not (archive_root() / ".staging").exists() or not any(
        (archive_root() / ".staging").iterdir()
    )


@pytest.mark.asyncio
async def test_run_archive_requires_known_reason() -> None:
    client = FakeClient()
    session = FakeDbSession()

    with pytest.raises(ValueError, match="reason"):
        await run_archive(client, session, "nb-1", "whim")

    client.notebooks.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_archive_never_deletes_local_rows() -> None:
    client = FakeClient(sources=[_source("src-1", "S", url="https://x.test")])
    session = FakeDbSession()

    await run_archive(client, session, "nb-1", "redundant")

    assert session.deleted == []
    for stmt in session.executed:
        assert isinstance(stmt, Select)
        assert "clauses" in str(stmt) or "embeddings" in str(stmt)


# --- failure handling ---------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_download_keeps_partial_and_blocks_delete() -> None:
    client = FakeClient(
        sources=[_source("src-1", "Source one", url="https://x.test")],
        artifacts=[_artifact("art-1", "Report")],
        failing_artifact_ids={"art-1"},
    )
    session = FakeDbSession()

    result = await run_archive(client, session, "nb-1", "redundant")

    assert result.final_path is None
    assert result.partial_path.exists(), "the partial tarball must be kept"
    assert not result.partial_path.with_name(result.partial_path.name[: -len(".partial")]).exists()
    assert result.failed_items and result.failed_items[0]["id"] == "art-1"
    client.notebooks.delete.assert_not_awaited()

    with pytest.raises(ValueError, match="not finalized"):
        await execute_archive_delete(client, session, result, "Test Notebook")


@pytest.mark.asyncio
async def test_failed_source_fulltext_blocks_finalize() -> None:
    client = FakeClient(
        sources=[_source("src-1", "Source one")],
        failing_source_ids={"src-1"},
    )
    session = FakeDbSession()

    result = await run_archive(client, session, "nb-1", "redundant")

    assert result.final_path is None
    assert result.partial_path.exists()
    assert [item["id"] for item in result.failed_items] == ["src-1"]


@pytest.mark.asyncio
async def test_generating_artifact_is_not_downloadable_but_does_not_block() -> None:
    client = FakeClient(
        sources=[_source("src-1", "Source one", url="https://x.test")],
        artifacts=[_artifact("art-1", "Audio", kind="audio", completed=False, prompt="p")],
    )
    session = FakeDbSession()

    result = await run_archive(client, session, "nb-1", "redundant")

    assert result.final_path is not None
    entry = next(item for item in result.manifest["items"] if item["id"] == "art-1")
    assert entry["status"] == STATUS_NOT_DOWNLOADABLE
    assert entry["kind"] == "audio"
    assert entry["artifact_status"] == "in_progress"
    assert entry["generation_prompt"] == "p"


# --- verification -------------------------------------------------------------


def _make_tarball(path: Path, files: dict[str, bytes]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        import io

        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


def test_verify_archive_passes_when_every_ok_entry_is_present() -> None:
    tmp = Path("/tmp/verify-ok-test.tar.gz")
    try:
        _make_tarball(tmp, {"sources/a.md": b"x" * 10, "manifest.json": b"{}"})
        manifest = {"items": [{"status": "ok", "archive_path": "sources/a.md"}]}
        result = verify_archive(tmp, manifest)
        assert result.ok is True
        assert result.file_count == 2
        assert result.total_bytes == 12
    finally:
        tmp.unlink(missing_ok=True)


def test_verify_archive_fails_on_missing_and_empty_entries() -> None:
    tmp = Path("/tmp/verify-missing-test.tar.gz")
    try:
        _make_tarball(tmp, {"sources/empty.md": b"", "manifest.json": b"{}"})
        manifest = {
            "items": [
                {"status": "ok", "archive_path": "sources/empty.md"},
                {"status": "ok", "archive_path": "sources/missing.md"},
                {"status": "failed", "archive_path": "sources/skipped.md"},
                {"status": "ok", "archive_path": None},
            ]
        }
        result = verify_archive(tmp, manifest)
        assert result.ok is False
        assert result.missing == ["sources/missing.md"]
        assert result.empty == ["sources/empty.md"]
    finally:
        tmp.unlink(missing_ok=True)


def test_verify_archive_fails_on_missing_manifest() -> None:
    tmp = Path("/tmp/verify-nomanifest-test.tar.gz")
    try:
        _make_tarball(tmp, {"sources/a.md": b"data"})
        result = verify_archive(tmp, {"items": []})
        assert result.ok is False
        assert "manifest.json" in result.missing
    finally:
        tmp.unlink(missing_ok=True)


def test_verify_archive_fails_on_unopenable_file(tmp_path: Path) -> None:
    bogus = tmp_path / "not-a-tar.tar.gz"
    bogus.write_bytes(b"garbage")
    result = verify_archive(bogus, {"items": []})
    assert result.ok is False
    assert result.file_count == 0


def test_finalize_archive_rejects_wrong_suffix(tmp_path: Path) -> None:
    from notebooklm._app.archive import VerifyResult

    with pytest.raises(ValueError, match="partial"):
        finalize_archive(
            tmp_path / "weird.tar", {}, VerifyResult(ok=True, file_count=1, total_bytes=1)
        )


def test_finalize_archive_keeps_partial_on_failed_verify(tmp_path: Path) -> None:
    from notebooklm._app.archive import VerifyResult

    partial = tmp_path / "nb.tar.gz.partial"
    partial.write_bytes(b"data")
    manifest = {"items": []}
    verify = VerifyResult(ok=False, file_count=0, total_bytes=0, missing=["x"])

    assert finalize_archive(partial, manifest, verify) is None
    assert partial.exists()


# --- record + remote delete ----------------------------------------------------


@pytest.mark.asyncio
async def test_record_archive_writes_both_rows(tmp_path: Path) -> None:
    session = FakeDbSession()
    manifest = {"notebook_id": "nb-1", "notebook_title": "T", "document_ids": ["s1"]}

    record_id = await record_archive(session, manifest, tmp_path / "a.tar.gz", "incorrect")

    assert record_id == 1
    archived = session.added[0]
    assert isinstance(archived, ArchivedNotebook)
    assert archived.document_ids == ["s1"]
    assert isinstance(session.added[1], RemovalLog)


@pytest.mark.asyncio
async def test_record_archive_requires_known_reason(tmp_path: Path) -> None:
    session = FakeDbSession()
    with pytest.raises(ValueError, match="reason"):
        await record_archive(
            session, {"notebook_id": "n", "notebook_title": "t"}, tmp_path / "a", "whim"
        )


def _finalized_result(record_id: int | None = 1) -> ArchiveResult:
    return ArchiveResult(
        notebook_id="nb-1",
        notebook_title="Test Notebook",
        reason="redundant",
        partial_path=Path("/tmp/x.tar.gz.partial"),
        final_path=Path("/tmp/x.tar.gz"),
        archive_record_id=record_id,
    )


@pytest.mark.asyncio
async def test_execute_archive_delete_requires_typed_title_match() -> None:
    client = FakeClient()
    session = FakeDbSession()
    result = _finalized_result()

    assert await execute_archive_delete(client, session, result, "nope wrong") is False

    client.notebooks.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_execute_archive_delete_deletes_and_flags_record() -> None:
    client = FakeClient()
    session = FakeDbSession()
    # Seed the record the way record_archive would have.
    session.add(
        ArchivedNotebook(
            notebook_id="nb-1",
            title="T",
            archive_path="p",
            document_ids=[],
            reason="redundant",
            remote_deleted=False,
        )
    )
    session.added[0].id = 7
    result = _finalized_result(record_id=7)

    assert await execute_archive_delete(client, session, result, "test note") is True

    client.notebooks.delete.assert_awaited_once_with("nb-1")
    assert session.added[0].remote_deleted is True


@pytest.mark.asyncio
async def test_execute_archive_delete_without_record_still_deletes() -> None:
    client = FakeClient()
    session = FakeDbSession()

    assert (
        await execute_archive_delete(client, session, _finalized_result(None), "Test Notebook")
        is True
    )
    client.notebooks.delete.assert_awaited_once()


# --- write_tarball ------------------------------------------------------------


def test_write_tarball_includes_staged_files(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    (staging / "sources").mkdir(parents=True)
    (staging / "sources" / "a.md").write_text("hello")
    dest = tmp_path / "out.tar.gz.partial"

    write_tarball(staging, dest)

    with tarfile.open(dest, "r:gz") as tar:
        assert "sources/a.md" in {member.name for member in tar.getmembers()}
