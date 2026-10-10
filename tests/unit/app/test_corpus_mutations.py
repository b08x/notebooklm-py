"""Confirmed delete and export against the real Postgres (facts 21-23, 25-26)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import corpus_mutations as cm
from notebooklm._app.fact_checks import record_not_checkworthy
from notebooklm.db.models import ChunkRun, Clause, Embedding, FactCheck, ParentChunk, RemovalLog
from tests._fixtures.corpus_seed import Seeder
from tests._fixtures.postgres import pg_session  # noqa: F401


@pytest.fixture
async def seeded(pg_session: AsyncSession):  # noqa: F811
    s = Seeder(pg_session)
    s.run_a = await s.ingest("a", "a one|a two||a three", params={"title": "Doc A"})
    s.run_b = await s.ingest("b", "b one|b two")
    return s


async def _count(session: AsyncSession, model: Any, cond: Any) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model).where(cond))).scalar_one()
    )


async def _clauses(session: AsyncSession, doc: str) -> list[Clause]:
    rows = await session.execute(
        select(Clause).where(Clause.document_id == doc).order_by(Clause.sentence_index)
    )
    return list(rows.scalars())


async def _logs(session: AsyncSession, item_ids: list[str]) -> list[RemovalLog]:
    rows = await session.execute(select(RemovalLog).where(RemovalLog.item_id.in_(item_ids)))
    return list(rows.scalars())


@pytest.mark.asyncio
async def test_preview_counts_and_changes_nothing(seeded: Seeder) -> None:
    s = seeded
    first = (await _clauses(s.session, s.doc("a")))[0]
    await record_not_checkworthy(s.session, first.external_id, job_id=None, trace_id=None)
    preview = await cm.delete_preview(s.session, "document", [s.doc("a")])
    assert preview["counts"] == {
        "clauses": 3,
        "embeddings": 3,
        "fact_checks": 1,
        "parents": 2,
        "runs": 1,
    }
    assert len(await _clauses(s.session, s.doc("a"))) == 3
    clause_preview = await cm.delete_preview(s.session, "clause", [first.external_id])
    assert clause_preview["counts"]["parents"] == 0 and clause_preview["counts"]["clauses"] == 1


@pytest.mark.asyncio
async def test_delete_clause_removes_embeddings_and_fact_checks(seeded: Seeder) -> None:
    s = seeded
    target = (await _clauses(s.session, s.doc("a")))[0]
    eid = target.external_id
    await record_not_checkworthy(s.session, eid, job_id=None, trace_id=None)
    receipt = await cm.delete(s.session, "clause", [eid], "redundant")
    assert receipt.counts.clauses == 1 and receipt.counts.embeddings == 1
    assert receipt.counts.fact_checks == 1
    assert await _count(s.session, Clause, Clause.external_id == eid) == 0
    assert await _count(s.session, Embedding, Embedding.clause_id == eid) == 0
    assert await _count(s.session, FactCheck, FactCheck.clause_external_id == eid) == 0
    logs = await _logs(s.session, [eid])
    assert len(logs) == 1
    log = logs[0]
    assert (log.item_type, log.action, log.reason) == ("clause", "delete_local", "redundant")
    assert log.notebook_id == s.notebook and log.item_title == "Doc A"
    assert receipt.to_dict()["removal_log_ids"] == [log.id]


@pytest.mark.asyncio
async def test_delete_parent_with_children(seeded: Seeder) -> None:
    s = seeded
    parent_id = (await _clauses(s.session, s.doc("a")))[0].parent_id
    receipt = await cm.delete(s.session, "parent", [parent_id], "experimental")
    assert (receipt.counts.clauses, receipt.counts.parents, receipt.counts.runs) == (2, 1, 0)
    assert [c.text for c in await _clauses(s.session, s.doc("a"))] == ["a three"]
    assert len(await _logs(s.session, [str(parent_id)])) == 1


@pytest.mark.asyncio
async def test_delete_run_and_document(seeded: Seeder) -> None:
    s = seeded
    run_receipt = await cm.delete(s.session, "run", [s.run_b], "other")
    assert run_receipt.counts.runs == 1 and run_receipt.counts.clauses == 2
    assert await _count(s.session, ChunkRun, ChunkRun.id == s.run_b) == 0
    assert len(await _logs(s.session, [str(s.run_b)])) == 1

    second_run = await s.ingest("a", "a again")
    doc_receipt = await cm.delete(s.session, "document", [s.doc("a")], "incorrect")
    assert doc_receipt.counts.runs == 2 and doc_receipt.counts.clauses == 4
    assert await _count(s.session, ChunkRun, ChunkRun.document_id == s.doc("a")) == 0
    assert await _count(s.session, ParentChunk, ParentChunk.run_id == second_run) == 0
    # One removal_log row per delete action (the document), not per run.
    assert len(await _logs(s.session, [s.doc("a")])) == 1


@pytest.mark.asyncio
async def test_busy_document_refused(seeded: Seeder) -> None:
    s = seeded
    with pytest.raises(cm.DeleteRefusedError):
        await cm.delete(
            s.session, "document", [s.doc("a")], "other", busy_document_ids={s.doc("a")}
        )
    with pytest.raises(cm.DeleteRefusedError):
        await cm.delete(s.session, "run", [s.run_a], "other", busy_document_ids={s.doc("a")})
    assert len(await _clauses(s.session, s.doc("a"))) == 3


@pytest.mark.parametrize(
    ("level", "ids", "reason"),
    [
        ("nope", ["x"], "other"),
        ("clause", ["x"], "bad"),
        ("clause", [], "other"),
        ("run", ["x"], "other"),
    ],
)
@pytest.mark.asyncio
async def test_validation(
    pg_session: AsyncSession,  # noqa: F811
    level: str,
    ids: list[str],
    reason: str,
) -> None:
    with pytest.raises(ValueError):
        await cm.delete_preview(pg_session, level, ids, reason)


@pytest.mark.asyncio
async def test_export_markdown_and_json(seeded: Seeder) -> None:
    s = seeded
    ids = [c.external_id for c in await _clauses(s.session, s.doc("a"))][:2]
    md = await cm.export(s.session, ids, "markdown")
    assert md["media_type"] == "text/markdown" and md["count"] == 2
    assert "## Doc A" in md["content"] and "> a one" in md["content"] and ids[0] in md["content"]
    js = await cm.export(s.session, list(reversed(ids)), "json")
    chunks = json.loads(js["content"])["chunks"]
    assert [c["external_id"] for c in chunks] == list(reversed(ids))
    with pytest.raises(ValueError):
        await cm.export(s.session, ids, "pdf")


class _Notes:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def create(self, notebook_id: str, title: str, content: str) -> Any:
        self.calls.append((notebook_id, title, content))
        return SimpleNamespace(id=f"note-{len(self.calls)}")


@pytest.mark.asyncio
async def test_export_to_note_per_notebook(seeded: Seeder) -> None:
    s = seeded
    other_run = await s.ingest("c", "c one", notebook="nb-other-" + s.prefix)
    assert other_run
    ids = [c.external_id for c in await _clauses(s.session, s.doc("a"))]
    ids += [c.external_id for c in await _clauses(s.session, s.doc("c"))]
    client = SimpleNamespace(notes=_Notes())
    created = await cm.export_to_note(client, s.session, ids)
    assert {c["notebook_id"] for c in created} == {s.notebook, "nb-other-" + s.prefix}
    assert sum(c["count"] for c in created) == 4
    assert all("> " in call[2] for call in client.notes.calls)
    with pytest.raises(ValueError):
        await cm.export_to_note(client, s.session, ["missing:0:0"])
