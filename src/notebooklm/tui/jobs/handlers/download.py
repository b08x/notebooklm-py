"""``download`` job handler: write a notebook's sources, chat history and artifacts to disk.

Each source and artifact is one job item. Items already recorded in ``LocalAsset``
(with the file still present) are skipped, so a retried job resumes where it stopped.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlalchemy import select

from notebooklm.client import NotebookLMClient
from notebooklm.db.models import LocalAsset
from notebooklm.db.session import async_session_maker

from ..runner import JobContext

logger = logging.getLogger(__name__)

#: Artifact kind -> (file suffix, ``client.artifacts`` download method).
ARTIFACT_FORMATS: dict[str, tuple[str, str]] = {
    "audio": (".wav", "download_audio"),
    "video": (".mp4", "download_video"),
    "report": (".md", "download_report"),
    "quiz": (".md", "download_quiz"),
    "flashcards": (".md", "download_flashcards"),
    "infographic": (".png", "download_infographic"),
    "slide_deck": (".pdf", "download_slide_deck"),
    "data_table": (".csv", "download_data_table"),
    "mind_map": (".md", "download_mind_map"),
}


def _safe_name(text: str) -> str:
    return "".join(c for c in text if c.isalnum() or c in (" ", "-", "_")).strip()


def _error_text(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


async def _is_downloaded(session: Any, asset_id: str) -> bool:
    result = await session.execute(select(LocalAsset).where(LocalAsset.asset_id == asset_id))
    asset = result.scalar_one_or_none()
    return bool(asset and os.path.exists(asset.local_path))


async def _upsert_asset(
    session: Any, notebook_id: str, asset_id: str, asset_type: str, local_path: str
) -> None:
    result = await session.execute(select(LocalAsset).where(LocalAsset.asset_id == asset_id))
    asset = result.scalar_one_or_none()
    if asset:
        asset.local_path = local_path
    else:
        session.add(
            LocalAsset(
                notebook_id=notebook_id,
                asset_id=asset_id,
                asset_type=asset_type,
                local_path=local_path,
            )
        )
    await session.commit()


async def download_notebook_assets(
    ctx: JobContext,
    notebook_id: str,
    *,
    out_root: Path,
    client_factory: Callable[[], Any] = NotebookLMClient.from_storage,
    session_factory: Callable[[], Any] = async_session_maker,
) -> str:
    """Download one notebook's sources, chat history and artifacts under ``out_root``."""
    async with client_factory() as client:
        await ctx.acquire_token()
        nb = await client.notebooks.get(notebook_id)
        title = getattr(nb, "title", "Unknown Notebook") or "Unknown Notebook"
        out_dir = out_root / f"{_safe_name(title)}_assets"
        sources_dir = out_dir / "sources"
        artifacts_dir = out_dir / "artifacts"
        sources_dir.mkdir(parents=True, exist_ok=True)
        artifacts_dir.mkdir(exist_ok=True)

        ctx.phase("Listing sources...", 0.0)
        await ctx.acquire_token()
        sources = await client.sources.list(notebook_id)

        async with session_factory() as session:
            for i, src in enumerate(sources):
                ctx.check_cancelled()
                src_title = _safe_name(getattr(src, "title", "") or "") or src.id
                item = ctx.add_item(src_title, "source")
                ctx.phase(f"Downloading source {i + 1}/{len(sources)}", i / len(sources) * 33)
                try:
                    if await _is_downloaded(session, src.id):
                        ctx.item_skipped(item, "already downloaded")
                        continue
                    await ctx.acquire_token()
                    ft = await client.sources.get_fulltext(
                        notebook_id, src.id, output_format="markdown"
                    )
                    if not ft.content:
                        ctx.item_skipped(item, "no content")
                        continue
                    path = sources_dir / f"{src_title}.md"
                    path.write_text(ft.content)
                    await _upsert_asset(
                        session, notebook_id, src.id, "source", str(path.absolute())
                    )
                    ctx.item_done(item, bytes=path.stat().st_size)
                except Exception as e:
                    logger.warning("Failed to download source %s: %s", src.id, e)
                    ctx.item_failed(item, _error_text(e))

            ctx.phase("Downloading chat history...", 33.0)
            try:
                await ctx.acquire_token()
                history = await client.chat.get_history(notebook_id)
                chat_text = "".join(
                    f"**User**: {user_turn}\n\n**AI**: {ai_turn}\n\n"
                    for user_turn, ai_turn, *_ in history
                )
                if chat_text:
                    (out_dir / "chat_history.md").write_text(chat_text)
            except Exception as e:
                logger.warning("Failed to download chat history for %s: %s", notebook_id, e)

            ctx.phase("Listing artifacts...", 66.0)
            try:
                await ctx.acquire_token()
                all_artifacts = await client.artifacts.list(notebook_id)
            except Exception as e:
                logger.warning("Failed to list artifacts for %s: %s", notebook_id, e)
                all_artifacts = []

            for i, artifact in enumerate(all_artifacts):
                ctx.check_cancelled()
                art_title = _safe_name(artifact.title or "") or artifact.id
                item = ctx.add_item(art_title, "artifact")
                ctx.phase(
                    f"Downloading artifact {i + 1}/{len(all_artifacts)}",
                    66 + i / len(all_artifacts) * 33,
                )
                try:
                    if await _is_downloaded(session, artifact.id):
                        ctx.item_skipped(item, "already downloaded")
                        continue
                    raw_kind = (
                        artifact.kind.value if hasattr(artifact.kind, "value") else artifact.kind
                    )
                    kind = str(raw_kind).lower()
                    if kind not in ARTIFACT_FORMATS:
                        ctx.item_skipped(item, f"unsupported kind {kind}")
                        continue
                    suffix, method = ARTIFACT_FORMATS[kind]
                    file_path = artifacts_dir / f"{art_title}{suffix}"
                    await ctx.acquire_token()
                    await getattr(client.artifacts, method)(
                        notebook_id, str(file_path), artifact.id
                    )
                    if not file_path.exists():
                        ctx.item_skipped(item, "no file written")
                        continue
                    await _upsert_asset(
                        session, notebook_id, artifact.id, "artifact", str(file_path.absolute())
                    )
                    ctx.item_done(item, bytes=file_path.stat().st_size)
                except Exception as e:
                    logger.warning("Failed to download artifact %s: %s", artifact.id, e)
                    ctx.item_failed(item, _error_text(e))

    ctx.phase(f"Assets downloaded to {out_dir}", 100.0)
    return f"Assets downloaded to {out_dir}"


async def handle(ctx: JobContext) -> str | None:
    if not ctx.notebook_id:
        raise ValueError("download job has no notebook_id")
    download_dir = ctx.payload.get("download_dir")
    out_root = Path(download_dir) if download_dir else Path.cwd()
    return await download_notebook_assets(ctx, ctx.notebook_id, out_root=out_root)
