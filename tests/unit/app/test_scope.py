"""Assessment on any corpus scope: sfl_tag and fact-check loaders (facts 49-50)."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app import sfl_tagging
from notebooklm._app.fact_checks import load_children
from notebooklm._app.scope import Scope
from notebooklm.db.models import Clause
from tests._fixtures.corpus_seed import Seeder
from tests._fixtures.postgres import pg_session  # noqa: F401


class _SessionFactory:
    """``async_sessionmaker`` stand-in that reuses the rolled-back test session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def __call__(self) -> Any:
        session = self.session

        class _Ctx:
            async def __aenter__(self) -> AsyncSession:
                return session

            async def __aexit__(self, *exc: object) -> None:
                return None

        return _Ctx()


class Engine:
    def forward(self, text: str) -> dict[str, Any]:
        return {
            "ideational": {"participants": [text]},
            "interpersonal": {"mood": "declarative", "modality": "high", "tenor": "neutral"},
        }


@pytest.fixture
async def seeded(pg_session: AsyncSession):  # noqa: F811
    s = Seeder(pg_session)
    s.run_src = await s.ingest("src", "s1|s2")
    s.run_note = await s.ingest("note", "n1", params={"kind": "note"})
    s.run_art = await s.ingest("art", "a1|a2", params={"kind": "report"})
    s.old_art = s.run_art
    s.run_art = await s.ingest("art", "a1|a2|a3", params={"kind": "report"})
    return s


def test_scope_from_mapping_and_describe() -> None:
    scope = Scope.from_mapping(
        {"document_ids": "a,b", "run_ids": ["3"], "external_ids": ["x"], "parent_id": "4"}
    )
    assert scope.document_ids == ("a", "b") and scope.run_ids == (3,) and scope.parent_id == 4
    assert scope.explicit and not scope.is_empty
    assert scope.describe() == "2 document(s), 1 run(s), 1 chunk(s), parent 4"
    assert Scope().describe() == "whole corpus" and Scope().is_empty
    assert Scope.from_mapping(None) == Scope()
    assert Scope(notebook_id="nb").to_dict()["notebook_id"] == "nb"


@pytest.mark.asyncio
async def test_fact_check_loader_by_document_run_and_selection(seeded: Seeder) -> None:
    s = seeded
    by_doc = await load_children(s.session, scope=Scope(document_ids=(s.doc("note"), s.doc("art"))))
    assert sorted(c.text for c in by_doc) == ["a1", "a2", "a3", "n1"]  # active runs only
    by_run = await load_children(s.session, scope=Scope(run_ids=(s.old_art,)))
    assert [c.text for c in by_run] == ["a1", "a2"]  # explicit run, even inactive
    ids = [c.external_id for c in by_doc if c.text in ("a3", "n1")]
    picked = await load_children(s.session, scope=Scope(external_ids=tuple(ids)))
    assert sorted(c.text for c in picked) == ["a3", "n1"]
    nb = await load_children(s.session, notebook_id=s.notebook)
    assert len(nb) == 6
    combo = await load_children(
        s.session, notebook_id=s.notebook, scope=Scope(document_ids=(s.doc("src"),))
    )
    assert sorted(c.text for c in combo) == ["s1", "s2"]


@pytest.mark.asyncio
async def test_sfl_tagging_touches_only_scoped_documents(seeded: Seeder) -> None:
    s = seeded
    factory = _SessionFactory(s.session)
    children = await sfl_tagging.load_children(factory, Scope(document_ids=(s.doc("art"),)))
    assert [c.text for c in children] == ["a1", "a2", "a3"]
    starts: list[tuple[int, int]] = []
    tagged, failed = await sfl_tagging.tag_children(
        children,
        session_factory=factory,  # type: ignore[arg-type]
        progress=sfl_tagging.GroupProgress(
            start=lambda n, total, idx, k: starts.append((n, k)),
            done=lambda h, k, f, e: None,
        ),
        engine=Engine(),
        lm=object(),
    )
    assert (tagged, failed) == (3, 0) and starts == [(1, 3)]
    rows = (
        await s.session.execute(
            select(Clause.document_id, Clause.sfl).where(Clause.document_id.like(f"{s.prefix}%"))
        )
    ).all()
    tagged_docs = {doc for doc, sfl in rows if sfl is not None}
    assert tagged_docs == {s.doc("art")}
    assert all(sfl["mood"] == "declarative" for doc, sfl in rows if sfl)

    nb_children = await sfl_tagging.load_children(factory, s.notebook)
    assert len(nb_children) == 6
