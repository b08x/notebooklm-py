"""Seed throwaway chunk runs into the live Postgres for Corpus Explorer tests.

Uses the real :class:`IngestionService` with an injected chunker, embedder and
feature extractor, so rows have the exact shape production ingestion writes.
Pair with ``tests._fixtures.postgres.pg_session`` (rolled back per test).

Every seeded id carries a per-test ``uuid`` prefix so parallel xdist workers
sharing the database never see each other's rows (they are uncommitted anyway).
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._preprocessing.chunking import ChildChunk, ChunkResult, ChunkStats, ParentChunk
from notebooklm._preprocessing.features import ClauseFeatures
from notebooklm._preprocessing.ingestion import IngestionService

DIM = 768


def unit_vector(seed: str) -> list[float]:
    """A deterministic unit vector derived from ``seed``."""
    digest = hashlib.sha256(seed.encode()).digest()
    raw = [((digest[i % len(digest)] + i * 7) % 251) / 251.0 - 0.5 for i in range(DIM)]
    norm = math.sqrt(sum(v * v for v in raw)) or 1.0
    return [v / norm for v in raw]


def nudged(vec: list[float], amount: float) -> list[float]:
    """``vec`` moved slightly along one axis and renormalised (a near-duplicate)."""
    out = list(vec)
    out[0] += amount
    norm = math.sqrt(sum(v * v for v in out))
    return [v / norm for v in out]


class SplitStrategy:
    """``"p1c1|p1c2||p2c1"`` → parents split on ``||``, children on ``|``."""

    name, version = "split", "1"
    params: dict[str, Any] = {}

    def chunk(self, text: str) -> ChunkResult:
        parents, offset = [], 0
        for block in text.split("||"):
            kids, pos = [], offset
            for piece in block.split("|"):
                kids.append(ChildChunk(piece, pos, pos + len(piece)))
                pos += len(piece) + 1
            parents.append(ParentChunk(block.replace("|", " "), offset, offset + len(block), kids))
            offset += len(block) + 2
        return ChunkResult(parents, ChunkStats())


class MapEmbedder:
    """Embeds by lookup in ``vectors`` (keyed by text), else a hash-derived vector."""

    def __init__(self, vectors: dict[str, list[float]] | None = None) -> None:
        self.vectors = vectors or {}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.vectors.get(t) or unit_vector(t) for t in texts]


def _features(texts: list[str]) -> list[ClauseFeatures]:
    out = []
    for t in texts:
        words = t.split()
        tokens = [
            {
                "text": w,
                "lemma": w.lower(),
                "pos": "PROPN" if w[:1].isupper() else "NOUN",
                "dep": "ROOT" if i == 0 else "dep",
                "head": 0,
            }
            for i, w in enumerate(words)
        ]
        groups = (
            {"noun_chunks": [{"text": words[0], "start": 0, "end": 1, "root": 0}]} if words else {}
        )
        out.append(ClauseFeatures(tokens, groups, 0))
    return out


def service(vectors: dict[str, list[float]] | None = None) -> IngestionService:
    return IngestionService(
        None,
        embedder=MapEmbedder(vectors),
        strategy=SplitStrategy(),
        features=_features,
        use_source_context=False,
    )


class Seeder:
    """Ingest helper bound to one session and one unique id prefix."""

    def __init__(self, session: AsyncSession, vectors: dict[str, list[float]] | None = None):
        self.session = session
        self.prefix = uuid.uuid4().hex[:10]
        self.vectors: dict[str, list[float]] = vectors or {}

    def doc(self, name: str) -> str:
        return f"{self.prefix}-{name}"

    @property
    def notebook(self) -> str:
        return f"nb-{self.prefix}"

    async def ingest(
        self,
        name: str,
        text: str,
        *,
        notebook: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> int:
        """Ingest ``text`` as document ``name``; returns the run id."""
        svc = service(self.vectors)
        result = await svc.ingest_document(
            self.session, self.doc(name), text, notebook_id=notebook or self.notebook
        )
        assert result is not None
        if params:
            from sqlalchemy import update

            from notebooklm.db.models import ChunkRun

            run = await self.session.get(ChunkRun, result.run_id)
            assert run is not None
            await self.session.execute(
                update(ChunkRun)
                .where(ChunkRun.id == result.run_id)
                .values(params={**(run.params or {}), **params})
            )
            await self.session.commit()
        return result.run_id


SeederFactory = Callable[..., Seeder]
