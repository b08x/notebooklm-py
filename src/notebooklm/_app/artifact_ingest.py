"""Ingest NotebookLM artifacts into the local corpus as their own documents.

Each artifact becomes a corpus document keyed by its artifact id, with
``chunk_runs.params = {"kind": <kind>, "artifact_id": ..., "title": ...,
"content_hash": ...}`` (no schema migration).

Conversion goes through a per-kind registry, :data:`CONVERTERS`:

* audio / video — downloaded, prepared as a temporary FLAC
  (:mod:`notebooklm._preprocessing.audio_prep`), transcribed with the chosen
  provider, and stored as ``[Speaker N] …`` turns; the FLAC is deleted
  afterwards and the downloaded original is never modified;
* report → Markdown; quiz / flashcards → ``Q:``/``A:`` items; mind map →
  indented outline; data table → ``column: value`` rows.

Infographics and slide decks are listed but have no converter yet
("image-only, not ingestible yet"); registering an image/audio/video embedder
later only adds an entry to :data:`CONVERTERS`.

**Checksum gate:** the downloaded bytes (audio/video) or converted text are
hashed *before* any transcription. When the document's active run already has
that hash, ingestion is skipped (``skipped_unchanged``) unless ``force``.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import os
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .._preprocessing.audio_prep import prepared_audio
from .._preprocessing.transcription import (
    TranscriptionOptions,
    build_adapter,
    speaker_turns,
)
from ..db.models import ChunkRun

#: Env var overriding the transcript cache directory.
ARTIFACTS_DIR_ENV = "NOTEBOOKLM_ARTIFACTS_DIR"
DEFAULT_ARTIFACTS_DIR = "~/NotebookLM/artifacts"

NOT_INGESTIBLE_REASON = "image-only, not ingestible yet"

#: ``transcribe(path, options) -> {"text", "diarization", "provider"}`` (sync, thread).
Transcriber = Callable[[str, TranscriptionOptions], dict[str, Any]]
Progress = Callable[[str], None]


@dataclass
class Converted:
    """A converter's output: content hash plus text or ready-made chunks."""

    content_hash: str
    #: Full text for the document chunker (``None`` when ``chunks`` is set).
    text: str | None = None
    #: Pre-split chunks stored 1:1 (transcript turns, quiz items, table rows).
    chunks: list[str] | None = None


@dataclass
class Converter:
    kind: str
    media: str  # "audio" | "video" | "text"
    fetch: Callable[[Any, str, Any, str], Awaitable[str]]
    """``fetch(client, notebook_id, artifact, workdir) -> local path``"""
    to_text: Callable[[str], Converted] | None = None
    """Text kinds: local file -> converted text/chunks."""


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# -- text converters ------------------------------------------------------


def report_to_text(path: str) -> Converted:
    text = Path(path).read_text(encoding="utf-8")
    return Converted(sha256_text(text), text=text)


def quiz_to_chunks(path: str) -> Converted:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    chunks = []
    for q in data.get("questions", []):
        options = q.get("answerOptions", [])
        correct = [o.get("text", "") for o in options if o.get("isCorrect")]
        lines = [f"Q: {q.get('question', '').strip()}"]
        if correct:
            lines.append(f"A: {'; '.join(correct)}")
        if q.get("hint"):
            lines.append(f"Hint: {q['hint']}")
        chunks.append("\n".join(lines))
    raw = json.dumps(data, sort_keys=True)
    return Converted(sha256_text(raw), chunks=[c for c in chunks if c.strip()])


def flashcards_to_chunks(path: str) -> Converted:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    chunks = [
        f"Q: {str(c.get('front', '')).strip()}\nA: {str(c.get('back', '')).strip()}"
        for c in data.get("cards", [])
    ]
    raw = json.dumps(data, sort_keys=True)
    return Converted(sha256_text(raw), chunks=chunks)


def _outline(node: Any, depth: int, out: list[str]) -> None:
    if isinstance(node, list):
        for child in node:
            _outline(child, depth, out)
        return
    if not isinstance(node, dict):
        return
    name = str(node.get("name") or node.get("title") or node.get("text") or "").strip()
    if name:
        out.append(f"{'  ' * depth}- {name}")
    for child in node.get("children") or []:
        _outline(child, depth + 1 if name else depth, out)


def mind_map_to_text(path: str) -> Converted:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    lines: list[str] = []
    _outline(data, 0, lines)
    text = "\n".join(lines)
    return Converted(sha256_text(text), text=text)


def data_table_to_chunks(path: str) -> Converted:
    raw = Path(path).read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(raw))
    rows = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows:
        return Converted(sha256_text(raw), chunks=[])
    header, body = rows[0], rows[1:]
    chunks = [
        " | ".join(f"{h.strip()}: {v.strip()}" for h, v in zip(header, row, strict=False))
        for row in body
    ]
    return Converted(sha256_text(raw), chunks=chunks)


# -- fetchers ---------------------------------------------------------------


def _download(method: str, suffix: str, **kwargs: Any) -> Callable[..., Awaitable[str]]:
    async def fetch(client: Any, notebook_id: str, artifact: Any, workdir: str) -> str:
        path = os.path.join(workdir, f"{artifact.id}{suffix}")
        await getattr(client.artifacts, method)(notebook_id, path, artifact.id, **kwargs)
        return path

    return fetch


CONVERTERS: dict[str, Converter] = {
    "audio": Converter("audio", "audio", _download("download_audio", ".m4a")),
    "video": Converter("video", "video", _download("download_video", ".mp4")),
    "report": Converter("report", "text", _download("download_report", ".md"), report_to_text),
    "quiz": Converter(
        "quiz", "text", _download("download_quiz", ".json", output_format="json"), quiz_to_chunks
    ),
    "flashcards": Converter(
        "flashcards",
        "text",
        _download("download_flashcards", ".json", output_format="json"),
        flashcards_to_chunks,
    ),
    "mind_map": Converter(
        "mind_map", "text", _download("download_mind_map", ".json"), mind_map_to_text
    ),
    "data_table": Converter(
        "data_table", "text", _download("download_data_table", ".csv"), data_table_to_chunks
    ),
}


def artifact_kind(artifact: Any) -> str:
    kind = getattr(artifact, "kind", None)
    return str(getattr(kind, "value", kind) or "unknown")


async def active_run_hashes(session: AsyncSession, document_id: str) -> set[str]:
    """``source_hash`` and ``params.content_hash`` of the document's active run."""
    run = (
        await session.execute(
            select(ChunkRun)
            .where(ChunkRun.document_id == document_id, ChunkRun.is_active.is_(True))
            .order_by(ChunkRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if run is None:
        return set()
    hashes = {run.source_hash}
    if (run.params or {}).get("content_hash"):
        hashes.add(str(run.params["content_hash"]))
    return hashes


async def list_ingestible(
    client: Any, notebook_id: str, session: AsyncSession | None = None
) -> list[dict[str, Any]]:
    """The notebook's artifacts with ``ingestible`` / ``reason`` and ingest state."""
    artifacts = await client.artifacts.list(notebook_id)
    out = []
    for a in artifacts:
        kind = artifact_kind(a)
        converter = CONVERTERS.get(kind)
        ready = bool(getattr(a, "is_completed", True))
        reason = None
        if converter is None:
            reason = NOT_INGESTIBLE_REASON
        elif not ready:
            reason = "not finished generating"
        ingested = bool(await active_run_hashes(session, a.id)) if session is not None else None
        out.append(
            {
                "id": a.id,
                "title": getattr(a, "title", "") or a.id,
                "kind": kind,
                "media": converter.media if converter else "image",
                "ingestible": reason is None,
                "reason": reason,
                "ingested": ingested,
                "created_at": a.created_at.isoformat() if getattr(a, "created_at", None) else None,
            }
        )
    return out


def default_transcriber(path: str, options: TranscriptionOptions) -> dict[str, Any]:
    return build_adapter(options).transcribe(path)


def _cache_dir() -> Path:
    return Path(os.environ.get(ARTIFACTS_DIR_ENV) or DEFAULT_ARTIFACTS_DIR).expanduser()


async def _transcribe_cached(
    path: str,
    artifact_id: str,
    content_hash: str,
    options: TranscriptionOptions,
    transcriber: Transcriber,
    progress: Progress,
    cache_dir: Path | None,
) -> dict[str, Any]:
    """Transcribe the prepared FLAC, reusing a cached result for the same bytes+provider."""
    cache = None
    if cache_dir is not None:
        cache = cache_dir / f"{artifact_id}.{content_hash[:16]}.{options.provider}.transcript.json"
        if cache.exists():
            progress("Using cached transcript")
            return dict(json.loads(cache.read_text(encoding="utf-8")))
    progress(f"Transcribing with {options.provider}")
    result = await asyncio.to_thread(transcriber, path, options)
    if cache is not None:
        try:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(result, default=str), encoding="utf-8")
        except OSError:
            pass
    return result


async def ingest_artifact(
    client: Any,
    session: AsyncSession,
    notebook_id: str,
    artifact_id: str,
    *,
    service: Any,
    options: TranscriptionOptions | None = None,
    force: bool = False,
    transcriber: Transcriber = default_transcriber,
    progress: Progress | None = None,
    cache_dir: Path | None | bool = True,
) -> dict[str, Any]:
    """Convert and ingest one artifact. Returns ``{status, run_id, n_children, ...}``.

    ``status`` is ``ingested`` or ``skipped_unchanged``. ``service`` is an
    :class:`~notebooklm._preprocessing.ingestion.IngestionService`.
    """
    report = progress or (lambda _msg: None)
    artifact = await client.artifacts.get(notebook_id, artifact_id)
    kind = artifact_kind(artifact)
    converter = CONVERTERS.get(kind)
    if converter is None:
        raise ValueError(f"{kind} artifacts are {NOT_INGESTIBLE_REASON}")
    title = getattr(artifact, "title", "") or artifact_id
    cache: Path | None = _cache_dir() if cache_dir is True else (cache_dir or None)
    opts = options or TranscriptionOptions.from_env()

    with tempfile.TemporaryDirectory(prefix="nblm-artifact-") as workdir:
        report(f"Downloading {kind}")
        path = await converter.fetch(client, notebook_id, artifact, workdir)
        if converter.to_text is None:
            converted = Converted(sha256_file(path))
        else:
            converted = converter.to_text(path)

        existing = await active_run_hashes(session, artifact_id)
        if not force and converted.content_hash in existing:
            report("Already ingested, unchanged")
            return {
                "status": "skipped_unchanged",
                "artifact_id": artifact_id,
                "kind": kind,
                "content_hash": converted.content_hash,
            }

        extra: dict[str, Any] = {}
        if converter.media in ("audio", "video"):
            report("Preparing FLAC (mono, 80 Hz high-pass, -19 LUFS)")
            with prepared_audio(path, workdir) as prep:
                result = await _transcribe_cached(
                    prep.path, artifact_id, converted.content_hash, opts, transcriber, report, cache
                )
                extra = {
                    "transcription": {
                        **opts.to_dict(),
                        "provider": result.get("provider", opts.provider),
                        "sample_rate": prep.sample_rate,
                        "subtype": prep.subtype,
                    }
                }
            converted.chunks = speaker_turns(result)

    params = {
        "kind": kind,
        "artifact_id": artifact_id,
        "title": title,
        "content_hash": converted.content_hash,
        **extra,
    }
    report("Chunking and embedding")
    if converted.chunks is not None:
        ingested = await service.ingest_chunks(
            session,
            artifact_id,
            converted.chunks,
            notebook_id=notebook_id,
            context="",
            params=params,
        )
    else:
        ingested = await service.ingest_document(
            session,
            artifact_id,
            converted.text or "",
            notebook_id=notebook_id,
            context="",
            params=params,
        )
    if ingested is None:
        return {"status": "empty", "artifact_id": artifact_id, "kind": kind, "n_children": 0}
    return {
        "status": "ingested",
        "artifact_id": artifact_id,
        "kind": kind,
        "run_id": ingested.run_id,
        "n_children": ingested.n_children,
        "content_hash": converted.content_hash,
    }
