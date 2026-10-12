#!/usr/bin/env python
"""Seed (or remove) a small fixture corpus in the local Postgres.

Used by the Corpus Explorer Playwright smoke test and for trying the UI without
a NotebookLM account or an embedder. Rows go through the real
``IngestionService`` with a deterministic hashing embedder (no Ollama) and a
plain-whitespace feature extractor (no spaCy), so they have production shape.

    uv run python scripts/seed_corpus_fixture.py --notebook nb-demo
    uv run python scripts/seed_corpus_fixture.py --notebook nb-demo --remove

Prints a JSON summary (notebook id, documents, run ids, chunk count).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
from typing import Any

from sqlalchemy import delete, or_, select, update

from notebooklm._app.notebook_titles import upsert_titles
from notebooklm._preprocessing.chunking import ChildChunk, ChunkResult, ChunkStats, ParentChunk
from notebooklm._preprocessing.features import ClauseFeatures
from notebooklm._preprocessing.ingestion import IngestionService
from notebooklm.db.models import ChunkRun, Clause, CorpusNotebook, RemovalLog
from notebooklm.db.session import async_session_maker

DIM = 768

DOCS: dict[str, dict[str, Any]] = {
    "pipeline": {
        "title": "Pipeline architecture notes",
        "kind": "source",
        "text": (
            "The architecture leans on mature Ruby libraries rather than Python services.|"
            "ruby-spacy and rwordnet provide a robust foundation for Named Entity Recognition "
            "and for enriching entities with WordNet synsets.|"
            "Retrieval fuses keyword and vector rankings before the generator sees any context."
            "||Named entities are vetoed from clause splits so multi-token spans stay intact.|"
            "The SFL engine reads the dependency parse to find the root of each clause.|"
            "Kernel panics at that layer usually mean the cgroup memory limit was hit."
        ),
    },
    "memory": {
        "title": "Container memory limits",
        "kind": "source",
        "text": (
            "The OOM killer picks the process with the largest resident set size first.|"
            "Containers vanish without a log line when the cgroup limit is exceeded.|"
            "Swap is disabled on the build hosts, so memory pressure kills jobs quickly."
            "||Entity recognition with spaCy pipelines needs about two gigabytes of memory.|"
            "NsMvbzsVTlHfstpSeMH70+Qn0nTeo4OkzXKd/43HBfE1ksw//KH7RVvrc1xYsVF/4iken9nTH+Nwu|"
            "0.273 0.327 0.307 0.404 0.337 0.410 0.373 0.428 Recite 0.215 0.318 0.209"
        ),
    },
    "podcast": {
        "title": "Deep dive: consciousness and longevity",
        "kind": "audio",
        "text": (
            "[Speaker 0] I swear to the great root user, this episode is about memory.|"
            "[Speaker 1] Oh, yeah.|"
            "[Speaker 0] Kernel panics at that layer usually mean the cgroup memory limit was hit.|"
            "[Speaker 1] Right, and the OOM killer picks the largest RSS first.|"
            "[Speaker 0] Longevity research might have the same problem with measurement."
        ),
    },
}

#: SFL output stored on every seeded chunk, so fact-check runs can start at once.
SFL = {
    "mood": "declarative",
    "modality": "high",
    "tenor": {"formality": "informal", "stance": "expert-to-peer"},
    "pass1": {"participants": ["kernel"], "processes": ["hit"], "circumstances": ["usually"]},
}


class HashEmbedder:
    """Bag-of-words hashing embedder: overlapping words → nearby unit vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * DIM
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                h = int(hashlib.md5(word.encode()).hexdigest(), 16)
                vec[h % DIM] += 1.0 if (h >> 12) % 2 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SplitStrategy:
    """Parents split on ``||``, children on ``|``."""

    name, version = "fixture_split", "1"
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


def _features(texts: list[str]) -> list[ClauseFeatures]:
    feats = []
    for text in texts:
        words = text.split()
        tokens = [
            {
                "text": w,
                "lemma": w.lower().strip(".,"),
                "pos": "PROPN" if w[:1].isupper() else "NOUN",
                "dep": "ROOT" if i == 0 else "dep",
                "head": 0,
            }
            for i, w in enumerate(words)
        ]
        groups = (
            {"noun_chunks": [{"text": words[0], "start": 0, "end": 1, "root": 0}]} if words else {}
        )
        feats.append(ClauseFeatures(tokens, groups, 0))
    return feats


def notebook_title(notebook: str) -> str:
    """Stored title of the fixture notebook (the Corpus Explorer shows titles, not ids)."""
    return f"Fixture notebook {notebook}"


async def seed(notebook: str) -> dict[str, Any]:
    service = IngestionService(
        None,
        embedder=HashEmbedder(),
        strategy=SplitStrategy(),
        features=_features,
        use_source_context=False,
        embedding_model_name="fixture-hash",
    )
    runs: dict[str, int] = {}
    async with async_session_maker() as session:
        for key, doc in DOCS.items():
            document_id = f"{notebook}-{key}"
            result = await service.ingest_document(
                session,
                document_id,
                doc["text"],
                notebook_id=notebook,
                context="",
                params={"kind": doc["kind"], "title": doc["title"]},
            )
            assert result is not None
            runs[document_id] = result.run_id
        await session.execute(
            update(Clause).where(Clause.document_id.like(f"{notebook}-%")).values(sfl=SFL)
        )
        await session.commit()
        await upsert_titles(session, {notebook: notebook_title(notebook)})
        n = len(
            (
                await session.execute(
                    select(Clause.id).where(Clause.document_id.like(f"{notebook}-%"))
                )
            ).all()
        )
    return {
        "notebook_id": notebook,
        "title": notebook_title(notebook),
        "documents": list(runs),
        "runs": runs,
        "chunks": n,
    }


async def remove(notebook: str) -> dict[str, Any]:
    async with async_session_maker() as session:
        await session.execute(delete(ChunkRun).where(ChunkRun.notebook_id == notebook))
        await session.execute(delete(Clause).where(Clause.document_id.like(f"{notebook}-%")))
        await session.execute(delete(CorpusNotebook).where(CorpusNotebook.notebook_id == notebook))
        await session.execute(
            delete(RemovalLog).where(
                or_(RemovalLog.notebook_id == notebook, RemovalLog.item_id.like(f"{notebook}-%"))
            )
        )
        await session.commit()
    return {"notebook_id": notebook, "removed": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notebook", default="nb-fixture", help="notebook id to seed under")
    parser.add_argument("--remove", action="store_true", help="delete the fixture instead")
    args = parser.parse_args()
    out = asyncio.run(remove(args.notebook) if args.remove else seed(args.notebook))
    print(json.dumps(out))


if __name__ == "__main__":
    main()
