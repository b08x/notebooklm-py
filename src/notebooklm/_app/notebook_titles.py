"""Corpus notebook titles: the last known title per notebook, stored in Postgres.

Backed by the ``corpus_notebooks`` table (see :class:`notebooklm.db.models.CorpusNotebook`).
Written at ingest and on every successful live ``notebooks.list()``, read by the
Corpus Explorer so notebook titles survive an unsigned-in server.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import CorpusNotebook

__all__ = ["stored_titles", "upsert_titles"]


async def upsert_titles(session: AsyncSession, titles: Mapping[str, str]) -> None:
    """Store ``{notebook_id: title}``, overwriting any previously stored title."""
    for notebook_id, title in titles.items():
        if not notebook_id or not title:
            continue
        stmt = insert(CorpusNotebook).values(notebook_id=notebook_id, title=str(title))
        stmt = stmt.on_conflict_do_update(
            index_elements=[CorpusNotebook.notebook_id], set_={"title": stmt.excluded.title}
        )
        await session.execute(stmt)
    await session.commit()


async def stored_titles(session: AsyncSession, ids: list[str]) -> dict[str, str]:
    """Stored titles for ``ids``; ids without a row are simply absent."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(CorpusNotebook.notebook_id, CorpusNotebook.title).where(
                CorpusNotebook.notebook_id.in_(ids)
            )
        )
    ).all()
    return {str(notebook_id): str(title) for notebook_id, title in rows}
