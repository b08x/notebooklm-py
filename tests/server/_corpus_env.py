"""Shared seed data, fakes and the ``env`` fixture for the corpus route tests."""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, or_, select, update

from notebooklm.db.models import ChunkRun, Clause, RemovalLog
from notebooklm.db.session import async_session_maker
from notebooklm.server._corpus import CorpusServices
from notebooklm.server.app import create_app
from tests._fixtures.corpus_seed import Seeder, nudged, service, unit_vector

from .conftest import TEST_TOKEN

HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}", "Host": "127.0.0.1"}
TAGGED = {"mood": "declarative", "modality": "high", "tenor": {"formality": "informal"}}
PLAIN = [{"text": "Water", "lemma": "water"}, {"text": "boils", "lemma": "boil"}]
HEDGED = [{"text": "It", "lemma": "it"}, {"text": "might", "lemma": "might"}]


# ---------------------------------------------------------------------------
# Seed + cleanup (committed rows under a unique prefix)
# ---------------------------------------------------------------------------


async def _seed() -> SimpleNamespace:
    async with async_session_maker() as session:
        s = Seeder(session)
        # Per-test vectors: committed seeds of parallel tests must not be near-duplicates.
        entity = unit_vector(f"entity-{s.prefix}")
        s.vectors.update(
            {
                "Named entity recognition uses spaCy": entity,
                "Entity recognition with spaCy pipelines": nudged(entity, 0.02),
            }
        )
        run_a = await s.ingest(
            "a",
            "Named entity recognition uses spaCy|Kernel panics hit the cgroup limit"
            "||The OOM killer picks the largest RSS",
            params={"title": "Doc A"},
        )
        run_b = await s.ingest(
            "b",
            "Entity recognition with spaCy pipelines|It might rain",
            notebook=f"nb2-{s.prefix}",
            params={"kind": "audio"},
        )
        ids = {
            c.text: c.external_id
            for c in (
                await session.execute(
                    select(Clause).where(Clause.document_id.like(f"{s.prefix}-%"))
                )
            ).scalars()
        }
        return SimpleNamespace(
            prefix=s.prefix,
            notebook=s.notebook,
            notebook2=f"nb2-{s.prefix}",
            run_a=run_a,
            run_b=run_b,
            doc_a=s.doc("a"),
            doc_b=s.doc("b"),
            ids=ids,
        )


async def _tag(prefix: str, tokens_for: dict[str, list[dict[str, Any]]] | None = None) -> None:
    async with async_session_maker() as session:
        await session.execute(
            update(Clause).where(Clause.document_id.like(f"{prefix}-%")).values(sfl=TAGGED)
        )
        for text, tokens in (tokens_for or {}).items():
            await session.execute(
                update(Clause)
                .where(Clause.document_id.like(f"{prefix}-%"), Clause.text == text)
                .values(tokens=tokens)
            )
        await session.commit()


async def _cleanup(prefix: str) -> None:
    async with async_session_maker() as session:
        await session.execute(delete(ChunkRun).where(ChunkRun.document_id.like(f"{prefix}%")))
        await session.execute(delete(Clause).where(Clause.document_id.like(f"{prefix}%")))
        await session.execute(
            delete(RemovalLog).where(
                or_(
                    RemovalLog.item_id.like(f"{prefix}%"),
                    RemovalLog.notebook_id.like(f"%{prefix}"),
                )
            )
        )
        await session.commit()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class Embedder:
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix
        self.threads: set[str] = set()

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.threads.add(threading.current_thread().name)
        return [unit_vector(f"entity-{self.prefix}") for _ in texts]


class Checker:
    framework_available = True

    async def check(self, claim: str, parent: str, sfl: Any, on_step: Any = None) -> Any:
        if on_step:
            on_step("stop", "running")
            on_step("stop", "done")
        return SimpleNamespace(
            verdict="supported",
            confidence=0.9,
            probabilities={"supported": 0.9},
            sift_steps={"find_coverage": {"coverage_summary": "agree"}},
            citations=[{"url": "https://x", "title": "x", "quote": "q"}],
            model="m",
        )


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ask(self, notebook_id: str, question: str, source_ids: Any = None) -> Any:
        self.calls.append({"nb": notebook_id, "q": question, "source_ids": source_ids})
        return SimpleNamespace(answer="It uses spaCy [C1].", conversation_id="c")


class FakeNotes:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, str]] = []

    async def create(self, nb: str, title: str, content: str) -> Any:
        self.created.append((nb, title, content))
        return SimpleNamespace(id="note-1")


class FakeArtifactsApi:
    def __init__(self, prefix: str) -> None:
        self.aid = f"{prefix}-report"

    def _art(self, aid: str) -> Any:
        kind = "report" if aid == self.aid else "infographic"
        return SimpleNamespace(
            id=aid, title="Briefing", kind=kind, is_completed=True, created_at=None
        )

    async def list(self, nb: str) -> list[Any]:
        return [self._art(self.aid), self._art("poster")]

    async def get(self, nb: str, aid: str) -> Any:
        return self._art(aid)

    async def download_report(self, nb: str, path: str, aid: str) -> str:
        Path(path).write_text("# Briefing\n\nReport body sentence.")
        return path


class FakeNotebooks:
    async def list(self) -> list[Any]:
        return []


class Engine:
    def forward(self, text: str) -> dict[str, Any]:
        return {"ideational": {}, "interpersonal": {"mood": "declarative", "modality": "high"}}


class FakeReact:
    def __init__(self, sig: Any, tools: list[Any], max_iters: int) -> None:
        self.tools = tools

    def __call__(self, **kw: Any) -> Any:
        self.tools[0]("spaCy")  # search_corpus, bridged back onto the server loop
        return SimpleNamespace(answer="nb answer [C1]", reasoning="r")


class FakeMCC:
    def __init__(self, sig: Any, M: int) -> None:  # noqa: N803 - dspy's own name
        self.M = M

    def __call__(self, completions: list[Any], **kw: Any) -> Any:
        assert len(completions) == self.M
        return SimpleNamespace(answer="merged [C1] [C2]")


async def _health() -> dict[str, Any]:
    return {"ok": True, "url": "http://ollama", "model": "m"}


async def _completion(**kw: Any) -> Any:
    async def gen() -> Any:
        for piece in ("Spa", "Cy [C1]"):
            yield {"choices": [{"delta": {"content": piece}}]}

    return gen()


@pytest.fixture
def seeded() -> Iterator[SimpleNamespace]:
    data = asyncio.run(_seed())
    try:
        yield data
    finally:
        asyncio.run(_cleanup(data.prefix))


@pytest.fixture
def env(seeded: SimpleNamespace, tmp_path: Path) -> Iterator[SimpleNamespace]:
    embedder = Embedder(seeded.prefix)
    client = SimpleNamespace(
        chat=FakeChat(),
        notes=FakeNotes(),
        artifacts=FakeArtifactsApi(seeded.prefix),
        notebooks=FakeNotebooks(),
    )
    services = CorpusServices(
        embedder=embedder,
        checker_factory=Checker,
        ingest_service_factory=lambda c: service(),
        sfl_engine_factory=Engine,
        lm=object(),
        react_factory=FakeReact,
        mcc_factory=FakeMCC,
        deep_sandbox_check=lambda: False,
        completion=_completion,
        embedder_health=_health,
        configure_llm=False,
        transcript_cache=None,
    )

    @asynccontextmanager
    async def factory() -> Any:
        yield client

    app = create_app(client_factory=factory, corpus_services=services)
    with TestClient(
        app, headers=HEADERS, client=("127.0.0.1", 5555), raise_server_exceptions=False
    ) as http:
        yield SimpleNamespace(
            http=http, app=app, services=services, client=client, embedder=embedder, **vars(seeded)
        )


def _nb(env: Any) -> dict[str, Any]:
    return {"notebook_ids": [env.notebook, env.notebook2]}


def _wait(predicate: Any, timeout: float = 5.0) -> None:
    import time

    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.02)


def _sse(http: TestClient, url: str, until: str, method: str = "GET", **kw: Any) -> list[dict]:
    events = []
    with http.stream(method, url, **kw) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        for line in resp.iter_lines():
            if line.startswith("data: "):
                event = json.loads(line[6:])
                events.append(event)
                if event["type"] == until:
                    break
    return events
