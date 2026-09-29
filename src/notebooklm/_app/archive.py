"""Archive-then-delete business logic.

Staged pipeline that fails closed:

1. Collect notebook content into a staging directory.
2. Write ``<name>.tar.gz.partial``.
3. Verify the tarball against the manifest.
4. Rename to ``.tar.gz`` only when there are zero ``failed`` items AND
   verification passed.
5. Delete the remote notebook only after that, and only after the user
   confirms by typing the notebook title.

Local Postgres data (clauses, embeddings, local assets) is never purged; an
``archived_notebooks`` row keeps the surviving document ids findable.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import shutil
import tarfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app.curation import REMOVAL_REASONS, title_confirmation_matches
from notebooklm.db.models import ArchivedNotebook, Clause, Embedding, RemovalLog

#: Statuses an archive manifest entry can carry.
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_NOT_DOWNLOADABLE = "not_downloadable"

#: Seconds between remote downloads — same conscious rate limiting as the
#: existing asset-download path.
DOWNLOAD_SPACING_SECONDS = 0.5

#: Artifact kind -> (download method on ``client.artifacts``, file extension).
#: Mirrors the kind table used by ``tui/views/notebook_detail.py``.
ARTIFACT_DOWNLOAD_METHODS: dict[str, tuple[str, str]] = {
    "audio": ("download_audio", ".wav"),
    "video": ("download_video", ".mp4"),
    "report": ("download_report", ".md"),
    "quiz": ("download_quiz", ".md"),
    "flashcards": ("download_flashcards", ".md"),
    "infographic": ("download_infographic", ".png"),
    "slide_deck": ("download_slide_deck", ".pdf"),
    "data_table": ("download_data_table", ".csv"),
    "mind_map": ("download_mind_map", ".md"),
}


def slugify(text: str) -> str:
    """Lowercase, collapse non-alphanumerics into dashes, trim dashes."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or "untitled"


def archive_root() -> Path:
    """Archive destination: ``$NOTEBOOKLM_ARCHIVE_DIR`` or ~/Archive/NotebookLM.

    The directory is created (including parents) if missing (fact 9).
    """
    env = os.environ.get("NOTEBOOKLM_ARCHIVE_DIR")
    root = Path(env) if env else Path.home() / "Archive" / "NotebookLM"
    root.mkdir(parents=True, exist_ok=True)
    return root


def archive_filename(title: str, notebook_id: str, date: datetime.date | None = None) -> str:
    """``<slugified-title>_<id[:8]>_<YYYYMMDD>.tar.gz`` (fact 9)."""
    date = date or datetime.date.today()
    return f"{slugify(title)}_{notebook_id[:8]}_{date:%Y%m%d}.tar.gz"


def _item_filename(title: str, item_id: str, ext: str) -> str:
    return f"{slugify(title)}_{item_id[:8]}{ext}"


def _created_at_iso(obj: Any) -> str | None:
    created = getattr(obj, "created_at", None)
    if created is None:
        return None
    if isinstance(created, datetime.datetime):
        return created.isoformat()
    return str(created)


def _artifact_kind(artifact: Any) -> str:
    kind = getattr(artifact, "kind", None)
    raw = getattr(kind, "value", None) or str(kind)
    return str(raw).lower()


def _artifact_status_str(artifact: Any) -> str:
    status = getattr(artifact, "status_str", None)
    if isinstance(status, str):
        return status
    return str(getattr(artifact, "status", "unknown"))


@dataclass
class VerifyResult:
    """Outcome of :func:`verify_archive` (fact 11)."""

    ok: bool
    file_count: int
    total_bytes: int
    missing: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)


@dataclass
class ArchiveResult:
    """Everything the TUI needs after an archive run."""

    notebook_id: str
    notebook_title: str
    reason: str
    partial_path: Path
    final_path: Path | None = None
    manifest: dict[str, Any] | None = None
    verify: VerifyResult | None = None
    document_ids: list[str] = field(default_factory=list)
    archive_record_id: int | None = None
    error: str | None = None

    @property
    def failed_items(self) -> list[dict[str, Any]]:
        if not self.manifest:
            return []
        return [
            item for item in self.manifest.get("items", []) if item.get("status") == STATUS_FAILED
        ]


async def collect_archive(
    client: Any,
    session: AsyncSession,
    notebook_id: str,
    staging: Path,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Collect notebook content into ``staging`` and return the manifest.

    ``progress_cb(done, total)`` fires after each item (fact 15).
    """
    notebook = await client.notebooks.get(notebook_id)
    notebook_title = getattr(notebook, "title", "") or "Untitled"
    sources = await client.sources.list(notebook_id)
    artifacts = await client.artifacts.list(notebook_id)
    notes = await client.notes.list(notebook_id)
    try:
        mind_maps = await client.mind_maps.list_note_backed(notebook_id)
    except Exception:
        mind_maps = []

    items: list[dict[str, Any]] = []
    total = len(sources) + len(artifacts) + len(notes) + len(mind_maps) + 2
    done = 0

    def _bump() -> None:
        nonlocal done
        done += 1
        if progress_cb:
            progress_cb(done, total)

    staging.mkdir(parents=True, exist_ok=True)

    # --- Sources: full text as markdown; originals recorded, not fetched ----
    sources_dir = staging / "sources"
    for src in sources:
        title = getattr(src, "title", None) or src.id
        path = sources_dir / _item_filename(title, src.id, ".md")
        entry: dict[str, Any] = {
            "id": src.id,
            "title": title,
            "type": "source",
            "created_at": _created_at_iso(src),
            "archive_path": None,
            "status": STATUS_FAILED,
            "error": None,
        }
        try:
            await asyncio.sleep(DOWNLOAD_SPACING_SECONDS)
            fulltext = await client.sources.get_fulltext(
                notebook_id, src.id, output_format="markdown"
            )
            content = getattr(fulltext, "content", None) or ""
            if not content:
                raise ValueError("source returned no content")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            entry["archive_path"] = path.relative_to(staging).as_posix()
            entry["status"] = STATUS_OK
        except Exception as exc:  # noqa: BLE001 — failed items block the delete
            entry["error"] = str(exc)
        items.append(entry)

        # Originals: the manifest records the URL for web sources; uploaded
        # files have no download RPC, so they are marked not_downloadable
        # (plan risk 1) and do not block the delete.
        url = getattr(src, "download_url", None) or getattr(src, "url", None)
        if url:
            entry["url"] = url
        else:
            items.append(
                {
                    "id": src.id,
                    "title": f"{title} (original)",
                    "type": "source_original",
                    "created_at": _created_at_iso(src),
                    "archive_path": None,
                    "status": STATUS_NOT_DOWNLOADABLE,
                    "error": "uploaded original bytes have no download RPC; full text is archived",
                }
            )
        _bump()

    # --- Artifacts: native format via the kind->method table ----------------
    artifacts_dir = staging / "artifacts"
    for artifact in artifacts:
        title = getattr(artifact, "title", None) or artifact.id
        kind = _artifact_kind(artifact)
        entry = {
            "id": artifact.id,
            "title": title,
            "type": "artifact",
            "kind": kind,
            "artifact_status": _artifact_status_str(artifact),
            "generation_prompt": getattr(artifact, "generation_prompt", None),
            "created_at": _created_at_iso(artifact),
            "archive_path": None,
            "status": STATUS_FAILED,
            "error": None,
        }
        # ``is_completed`` is a property on the real ``Artifact`` type; test
        # fakes may expose it as a plain callable instead.
        is_completed = getattr(artifact, "is_completed", None)
        if is_completed is not None:
            completed = is_completed() if callable(is_completed) else bool(is_completed)
        else:
            completed = True
        if not completed:
            # Still generating or failed generation (fact 20): recorded, not
            # downloaded, never blocks the delete.
            entry["status"] = STATUS_NOT_DOWNLOADABLE
            entry["error"] = f"artifact not downloadable while in status {entry['artifact_status']}"
            items.append(entry)
            _bump()
            continue
        method_ext = ARTIFACT_DOWNLOAD_METHODS.get(kind)
        if method_ext is None:
            entry["status"] = STATUS_NOT_DOWNLOADABLE
            entry["error"] = f"no download method for artifact kind {kind!r}"
            items.append(entry)
            _bump()
            continue
        method, ext = method_ext
        path = artifacts_dir / _item_filename(title, artifact.id, ext)
        try:
            await asyncio.sleep(DOWNLOAD_SPACING_SECONDS)
            await getattr(client.artifacts, method)(notebook_id, str(path), artifact.id)
            if not path.is_file() or path.stat().st_size == 0:
                raise ValueError(f"download method produced no file at {path}")
            entry["archive_path"] = path.relative_to(staging).as_posix()
            entry["status"] = STATUS_OK
        except Exception as exc:  # noqa: BLE001
            entry["error"] = str(exc)
        items.append(entry)
        _bump()

    # --- Notes and note-backed mind maps ------------------------------------
    notes_dir = staging / "notes"
    for note in notes:
        title = getattr(note, "title", None) or note.id
        path = notes_dir / _item_filename(title, note.id, ".md")
        entry = {
            "id": note.id,
            "title": title,
            "type": "note",
            "created_at": _created_at_iso(note),
            "archive_path": None,
            "status": STATUS_OK,
            "error": None,
        }
        try:
            content = f"# {title}\n\n{getattr(note, 'content', '') or ''}\n"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            entry["archive_path"] = path.relative_to(staging).as_posix()
        except Exception as exc:  # noqa: BLE001
            entry["status"] = STATUS_FAILED
            entry["error"] = str(exc)
        items.append(entry)
        _bump()

    mind_maps_dir = staging / "mind_maps"
    for mind_map in mind_maps:
        title = getattr(mind_map, "title", None) or mind_map.id
        path = mind_maps_dir / _item_filename(title, mind_map.id, ".json")
        entry = {
            "id": mind_map.id,
            "title": title,
            "type": "mind_map",
            "created_at": _created_at_iso(mind_map),
            "archive_path": None,
            "status": STATUS_OK,
            "error": None,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(getattr(mind_map, "tree", None) or {}, indent=2), encoding="utf-8"
            )
            entry["archive_path"] = path.relative_to(staging).as_posix()
        except Exception as exc:  # noqa: BLE001
            entry["status"] = STATUS_FAILED
            entry["error"] = str(exc)
        items.append(entry)
        _bump()

    # --- Chat history --------------------------------------------------------
    chat_entry: dict[str, Any] = {
        "id": "chat_history",
        "title": "Chat history",
        "type": "chat",
        "archive_path": None,
        "status": STATUS_OK,
        "error": None,
    }
    try:
        await asyncio.sleep(DOWNLOAD_SPACING_SECONDS)
        history = await client.chat.get_history(notebook_id)
        if history:
            path = staging / "chat_history.md"
            path.write_text(
                "".join(
                    f"**User**: {user}\n\n**AI**: {answer}\n\n" for user, answer, *_ in history
                ),
                encoding="utf-8",
            )
            chat_entry["archive_path"] = path.relative_to(staging).as_posix()
    except Exception as exc:  # noqa: BLE001
        chat_entry["status"] = STATUS_FAILED
        chat_entry["error"] = str(exc)
    items.append(chat_entry)
    _bump()

    # --- Local clause/embedding export (fact 19) -----------------------------
    document_ids = sorted(
        {src.id for src in sources}
        | {artifact.id for artifact in artifacts}
        | {note.id for note in notes}
    )
    db_entry: dict[str, Any] = {
        "id": "db_export",
        "title": "Local clause/embedding export",
        "type": "db_export",
        "archive_path": None,
        "status": STATUS_OK,
        "error": None,
    }
    try:
        db_dir = staging / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        clause_rows = list(
            (
                await session.execute(select(Clause).where(Clause.document_id.in_(document_ids)))
            ).scalars()
        )
        if clause_rows:
            clauses_path = db_dir / "clauses.jsonl"
            clauses_path.write_text(
                "".join(
                    json.dumps(
                        {
                            "id": row.id,
                            "external_id": row.external_id,
                            "document_id": row.document_id,
                            "text": row.text,
                            "sentence_index": row.sentence_index,
                            "root_index": row.root_index,
                        }
                    )
                    + "\n"
                    for row in clause_rows
                ),
                encoding="utf-8",
            )
            embeddings = list(
                (
                    await session.execute(
                        select(Embedding).where(
                            Embedding.clause_id.in_([row.external_id for row in clause_rows])
                        )
                    )
                ).scalars()
            )
            if embeddings:
                embeddings_path = db_dir / "embeddings.jsonl"
                embeddings_path.write_text(
                    "".join(
                        json.dumps(
                            {
                                "id": row.id,
                                "clause_id": row.clause_id,
                                "model": row.model,
                                "embedding": _embedding_to_list(row.embedding),
                            }
                        )
                        + "\n"
                        for row in embeddings
                    ),
                    encoding="utf-8",
                )
            db_entry["archive_path"] = "db/clauses.jsonl"
    except Exception as exc:  # noqa: BLE001
        db_entry["status"] = STATUS_FAILED
        db_entry["error"] = str(exc)
    items.append(db_entry)
    _bump()

    manifest = {
        "notebook_id": notebook_id,
        "notebook_title": notebook_title,
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "document_ids": document_ids,
        "items": items,
    }
    return manifest


def _embedding_to_list(embedding: Any) -> list[Any]:
    try:
        return list(embedding)
    except Exception:
        return []


def write_tarball(staging: Path, dest_partial: Path) -> None:
    """Write every staged file into ``<name>.tar.gz.partial``."""
    dest_partial.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(dest_partial, "w:gz") as tar:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                tar.add(path, arcname=path.relative_to(staging).as_posix())


def verify_archive(path: Path, manifest: dict[str, Any]) -> VerifyResult:
    """Check the tarball opens and every ``ok`` entry is present, non-empty.

    Also requires ``manifest.json`` itself to be present with non-zero size
    (fact 11).
    """
    try:
        with tarfile.open(path, "r:gz") as tar:
            members = {member.name: member.size for member in tar.getmembers()}
    except Exception:
        return VerifyResult(ok=False, file_count=0, total_bytes=0, missing=[str(path)])
    missing: list[str] = []
    empty: list[str] = []
    for item in manifest.get("items", []):
        if item.get("status") != STATUS_OK:
            continue
        archive_path = item.get("archive_path")
        if not archive_path:
            continue
        if archive_path not in members:
            missing.append(archive_path)
        elif members[archive_path] <= 0:
            empty.append(archive_path)
    if "manifest.json" not in members or members["manifest.json"] <= 0:
        missing.append("manifest.json")
    return VerifyResult(
        ok=not missing and not empty,
        file_count=len(members),
        total_bytes=sum(members.values()),
        missing=missing,
        empty=empty,
    )


def finalize_archive(partial: Path, manifest: dict[str, Any], verify: VerifyResult) -> Path | None:
    """Promote ``.tar.gz.partial`` to ``.tar.gz`` when safe (fact 12).

    Requires zero ``failed`` items AND a passing verification; otherwise the
    ``.partial`` file is kept and ``None`` is returned.
    """
    failed = [item for item in manifest.get("items", []) if item.get("status") == STATUS_FAILED]
    if failed or not verify.ok:
        return None
    suffix = ".tar.gz.partial"
    if not partial.name.endswith(suffix):
        raise ValueError(f"partial archive must end with {suffix!r}, got {partial.name!r}")
    final = partial.with_name(partial.name[: -len(".partial")])
    os.replace(partial, final)
    return final


async def record_archive(
    session: AsyncSession,
    manifest: dict[str, Any],
    archive_path: Path,
    reason: str,
    *,
    remote_deleted: bool = False,
) -> int:
    """Write the ``archived_notebooks`` row and its ``removal_log`` entry."""
    if reason not in REMOVAL_REASONS:
        raise ValueError(f"reason must be one of {REMOVAL_REASONS}, got {reason!r}")
    record = ArchivedNotebook(
        notebook_id=manifest["notebook_id"],
        title=manifest["notebook_title"],
        archive_path=str(archive_path),
        document_ids=list(manifest.get("document_ids", [])),
        reason=reason,
        remote_deleted=remote_deleted,
    )
    session.add(record)
    session.add(
        RemovalLog(
            notebook_id=manifest["notebook_id"],
            notebook_title=manifest["notebook_title"],
            item_id=manifest["notebook_id"],
            item_title=manifest["notebook_title"],
            item_type="notebook",
            action="archive",
            reason=reason,
            archive_path=str(archive_path),
        )
    )
    await session.commit()
    return record.id


async def execute_archive_delete(
    client: Any,
    session: AsyncSession,
    archive_result: ArchiveResult,
    typed_title: str,
) -> bool:
    """Delete the remote notebook after typed-title confirmation (fact 13).

    Refuses (returns ``False``) when the typed title does not match, and
    raises when the archive was never finalized. On success the archived-
    notebook record flips to ``remote_deleted=True``.
    """
    if archive_result.final_path is None:
        raise ValueError("archive was not finalized; refusing to delete the remote notebook")
    if not title_confirmation_matches(archive_result.notebook_title, typed_title):
        return False
    await client.notebooks.delete(archive_result.notebook_id)
    if archive_result.archive_record_id is not None:
        record = await session.get(ArchivedNotebook, archive_result.archive_record_id)
        if record is not None:
            record.remote_deleted = True
            await session.commit()
    return True


async def run_archive(
    client: Any,
    session: AsyncSession,
    notebook_id: str,
    reason: str,
    progress_cb: Callable[[int, int], None] | None = None,
) -> ArchiveResult:
    """Full staged archive run: collect, tar, verify, finalize, record.

    Raises ``ValueError`` for an invalid reason before any work starts. The
    staging directory is removed afterwards; on failure the ``.partial``
    tarball is kept (fact 12).
    """
    if reason not in REMOVAL_REASONS:
        raise ValueError(f"reason must be one of {REMOVAL_REASONS}, got {reason!r}")

    notebook = await client.notebooks.get(notebook_id)
    notebook_title = getattr(notebook, "title", "") or "Untitled"
    root = archive_root()
    filename = archive_filename(notebook_title, notebook_id)
    partial_path = root / f"{filename}.partial"
    staging = root / ".staging" / f"{slugify(notebook_title)}_{notebook_id[:8]}"
    result = ArchiveResult(
        notebook_id=notebook_id,
        notebook_title=notebook_title,
        reason=reason,
        partial_path=partial_path,
    )
    try:
        manifest = await collect_archive(client, session, notebook_id, staging, progress_cb)
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        write_tarball(staging, partial_path)
        verify = verify_archive(partial_path, manifest)
        result.manifest = manifest
        result.verify = verify
        result.document_ids = list(manifest.get("document_ids", []))
        final = finalize_archive(partial_path, manifest, verify)
        if final is not None:
            result.final_path = final
            result.archive_record_id = await record_archive(session, manifest, final, reason)
    except Exception as exc:  # noqa: BLE001 — surfaced to the TUI as a failed archive
        result.error = str(exc)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return result
