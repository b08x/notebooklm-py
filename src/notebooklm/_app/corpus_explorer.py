"""Corpus Explorer queries: search, browse, facets, detail, neighbors, runs, map.

The read side of the web Corpus Explorer (served by ``notebooklm-server`` at
``/ui``). Every function takes an open ``AsyncSession`` and returns plain dicts,
matching :mod:`notebooklm._app.corpus`. Nothing here calls an LLM or
``dspy.configure()``, so the REST server may run these concurrently.

Scope: the whole local corpus. :class:`CorpusFilters` narrows it by notebook,
document, run, strategy, document kind, fact-check status, length, quality
(noise) flag and near-duplicate presence. By default only active runs count.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, fields, replace
from typing import Any

import httpx
from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    case,
    exists,
    func,
    literal_column,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .._preprocessing.embeddings import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    EmbeddingAdapter,
)
from ..db.models import ChunkRun, Clause, Embedding, FactCheck, ParentChunk, Topic
from .clause_search import ranked_search
from .noise import QUALITY_VALUES, classify_noise, noise_sql
from .sfl_format import format_sfl

logger = logging.getLogger(__name__)

#: L2 distance below which two chunk embeddings count as near-duplicates.
#: Embeddings are unit-normalised (embeddinggemma), so L2 lies in ``[0, 2]``;
#: 0.2 corresponds to a cosine similarity of about 0.98.
NEAR_DUP_L2 = 0.2

#: Default and maximum page size for :func:`browse`.
DEFAULT_PAGE = 100
MAX_PAGE = 500

#: Length buckets (chars) for the Browse length facet: ``(label, min, max_exclusive)``.
LENGTH_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("<80", 0, 80),
    ("80-300", 80, 300),
    ("300-1000", 300, 1000),
    ("1000+", 1000, None),
)

#: Values of the fact-check facet.
FACT_CHECK_STATUSES = ("unchecked", "passed", "failed", "other")

#: Document kinds (``chunk_runs.params->>'kind'``; missing = ``source``).
DOCUMENT_KINDS = (
    "source",
    "note",
    "audio",
    "video",
    "report",
    "quiz",
    "flashcards",
    "mind_map",
    "data_table",
)

#: Neighbor context lines shown either side of a chunk.
CONTEXT_LINES = 2


class ChunkNotFoundError(LookupError):
    """No clause with that external id."""


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


@dataclass
class CorpusFilters:
    """Browse/search narrowing. Empty lists mean "no restriction"."""

    notebook_ids: list[str] = field(default_factory=list)
    document_ids: list[str] = field(default_factory=list)
    run_ids: list[int] = field(default_factory=list)
    external_ids: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    fact_check: list[str] = field(default_factory=list)
    quality: list[str] = field(default_factory=list)
    min_len: int | None = None
    max_len: int | None = None
    has_near_duplicate: bool = False
    active_only: bool = True
    #: Case-insensitive substring filter on the chunk text.
    text: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> CorpusFilters:
        """Build from a JSON-ish mapping, ignoring unknown keys and empty values."""
        if not data:
            return cls()
        known = {f.name for f in fields(cls)}
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            if key not in known or value is None:
                continue
            if key == "run_ids":
                value = [int(v) for v in _as_list(value)]
            elif key in ("min_len", "max_len"):
                value = int(value)
            elif key in ("has_near_duplicate", "active_only"):
                value = _as_bool(value)
            elif key == "text":
                value = str(value) or None
            else:
                value = [str(v) for v in _as_list(value)]
            kwargs[key] = value
        return cls(**kwargs)


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, str):
        return [v for v in value.split(",") if v]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _kind_expr() -> ColumnElement[str]:
    return func.coalesce(ChunkRun.params["kind"].astext, "source")


def _fact_check_expr() -> ColumnElement[str]:
    any_check = exists().where(FactCheck.clause_external_id == Clause.external_id)
    return case(
        (Clause.fact_check_passed.is_(True), "passed"),
        (Clause.fact_check_passed.is_(False), "failed"),
        (any_check, "other"),
        else_="unchecked",
    )


def _length_bucket_expr() -> ColumnElement[str]:
    length = func.length(Clause.text)
    whens = []
    for label, low, high in LENGTH_BUCKETS:
        if high is None:
            whens.append((length >= low, label))
        else:
            whens.append((and_(length >= low, length < high), label))
    return case(*whens, else_=LENGTH_BUCKETS[-1][0])


def near_duplicate_exists(threshold: float = NEAR_DUP_L2) -> ColumnElement[bool]:
    """``EXISTS``: the clause has another chunk within ``threshold`` L2 distance.

    Uses an ``ORDER BY <-> LIMIT 1`` lateral so the HNSW index serves the lookup.
    Older runs of the same document are ignored (they are trivially identical).
    """
    sql = (
        "EXISTS (SELECT 1 FROM embeddings AS nd_self"
        " JOIN LATERAL (SELECT nd_e.embedding <-> nd_self.embedding AS d"
        " FROM embeddings AS nd_e JOIN clauses AS nd_c ON nd_c.external_id = nd_e.clause_id"
        " WHERE nd_e.clause_id <> nd_self.clause_id"
        " AND NOT (nd_c.document_id = clauses.document_id"
        " AND nd_c.run_id IS DISTINCT FROM clauses.run_id)"
        " ORDER BY nd_e.embedding <-> nd_self.embedding LIMIT 1) AS nd_nn ON true"
        f" WHERE nd_self.clause_id = clauses.external_id AND nd_nn.d < {float(threshold)!r})"
    )
    return literal_column(sql)


def _conditions(filters: CorpusFilters) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if filters.active_only:
        conds.append(ChunkRun.is_active.is_(True))
    if filters.notebook_ids:
        conds.append(ChunkRun.notebook_id.in_(filters.notebook_ids))
    if filters.document_ids:
        conds.append(Clause.document_id.in_(filters.document_ids))
    if filters.run_ids:
        conds.append(Clause.run_id.in_(filters.run_ids))
    if filters.external_ids:
        conds.append(Clause.external_id.in_(filters.external_ids))
    if filters.strategies:
        conds.append(ChunkRun.strategy.in_(filters.strategies))
    if filters.kinds:
        conds.append(_kind_expr().in_(filters.kinds))
    if filters.fact_check:
        conds.append(_fact_check_expr().in_(filters.fact_check))
    if filters.quality:
        conds.append(noise_sql().in_(filters.quality))
    if filters.min_len is not None:
        conds.append(func.length(Clause.text) >= filters.min_len)
    if filters.max_len is not None:
        conds.append(func.length(Clause.text) <= filters.max_len)
    if filters.text:
        conds.append(Clause.text.ilike(f"%{filters.text}%"))
    if filters.has_near_duplicate:
        conds.append(near_duplicate_exists())
    return conds


def apply_filters(stmt: Select[Any], filters: CorpusFilters) -> Select[Any]:
    """Join ``chunk_runs`` and add every filter condition to a ``select(Clause…)``."""
    stmt = stmt.join(ChunkRun, ChunkRun.id == Clause.run_id, isouter=True)
    conds = _conditions(filters)
    return stmt.where(*conds) if conds else stmt


# ---------------------------------------------------------------------------
# Row shaping
# ---------------------------------------------------------------------------


def _row(clause: Clause, run: ChunkRun | None, fact_check: str) -> dict[str, Any]:
    return {
        "id": clause.id,
        "external_id": clause.external_id,
        "text": clause.text,
        "document_id": clause.document_id,
        "run_id": clause.run_id,
        "parent_id": clause.parent_id,
        "sentence_index": clause.sentence_index,
        "notebook_id": run.notebook_id if run else None,
        "strategy": run.strategy if run else None,
        "kind": (run.params or {}).get("kind", "source") if run else "source",
        "title": (run.params or {}).get("title") if run else None,
        "is_active": run.is_active if run else False,
        "length": len(clause.text),
        "quality": classify_noise(clause.text) or "clean",
        "fact_check": fact_check,
        "has_sfl": clause.sfl is not None,
    }


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


async def search(
    session: AsyncSession,
    query: str,
    *,
    mode: str = "hybrid",
    filters: CorpusFilters | None = None,
    top_k: int = 25,
    embedder: EmbeddingAdapter | None = None,
) -> dict[str, Any]:
    """Keyword / vector / hybrid-RRF search over the (filtered) corpus.

    Each hit carries ``kw_rank``, ``vec_rank`` and the fused ``score``; the
    result carries ``vector_leg_ok`` (``False`` when the embedder is down and
    hybrid search fell back to the keyword leg).
    """
    flt = filters or CorpusFilters()
    started = asyncio.get_running_loop().time()
    result = await ranked_search(
        session,
        query,
        mode=mode,
        top_k=top_k,
        embedder=embedder,
        scope=lambda stmt: apply_filters(stmt, flt),
    )
    rows = await _rows_for(session, [h.clause_id for h in result.hits])
    hits = []
    for hit in result.hits:
        row = rows.get(hit.clause_id)
        if row is None:  # pragma: no cover - deleted between the two queries
            continue
        hits.append(
            {
                **row,
                "kw_rank": hit.kw_rank,
                "vec_rank": hit.vec_rank,
                "score": hit.score,
                "distance": hit.distance,
            }
        )
    elapsed_ms = round((asyncio.get_running_loop().time() - started) * 1000)
    return {
        "query": query,
        "mode": mode,
        "hits": hits,
        "vector_leg_ok": result.vector_leg_ok,
        "keyword_count": result.keyword_count,
        "vector_count": result.vector_count,
        "elapsed_ms": elapsed_ms,
    }


async def _rows_for(session: AsyncSession, external_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not external_ids:
        return {}
    fc = _fact_check_expr().label("fc")
    stmt = (
        select(Clause, ChunkRun, fc)
        .join(ChunkRun, ChunkRun.id == Clause.run_id, isouter=True)
        .where(Clause.external_id.in_(external_ids))
    )
    return {
        clause.external_id: _row(clause, run, status)
        for clause, run, status in (await session.execute(stmt)).all()
    }


# ---------------------------------------------------------------------------
# Browse + facets
# ---------------------------------------------------------------------------


async def browse(
    session: AsyncSession,
    filters: CorpusFilters | None = None,
    *,
    cursor: int | None = None,
    limit: int = DEFAULT_PAGE,
    with_total: bool = True,
) -> dict[str, Any]:
    """One keyset page of clauses ordered by id (``cursor`` = last id seen)."""
    flt = filters or CorpusFilters()
    limit = max(1, min(limit, MAX_PAGE))
    fc = _fact_check_expr().label("fc")
    stmt = apply_filters(select(Clause, ChunkRun, fc), flt)
    if cursor is not None:
        stmt = stmt.where(Clause.id > cursor)
    stmt = stmt.order_by(Clause.id).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    page = [_row(c, r, s) for c, r, s in rows[:limit]]
    total = None
    if with_total:
        count_stmt = apply_filters(select(func.count(Clause.id)), flt)
        total = int((await session.execute(count_stmt)).scalar_one())
    return {
        "items": page,
        "next_cursor": page[-1]["id"] if len(rows) > limit else None,
        "total": total,
    }


_FACETS: dict[str, tuple[dict[str, Any], Any]] = {
    # facet name -> (filter fields cleared while counting it, value expression)
    "notebook": ({"notebook_ids": []}, lambda: ChunkRun.notebook_id),
    "document": ({"document_ids": []}, lambda: Clause.document_id),
    "run": ({"run_ids": []}, lambda: Clause.run_id),
    "strategy": ({"strategies": []}, lambda: ChunkRun.strategy),
    "kind": ({"kinds": []}, _kind_expr),
    "fact_check": ({"fact_check": []}, _fact_check_expr),
    "quality": ({"quality": []}, noise_sql),
    "length": ({"min_len": None, "max_len": None}, _length_bucket_expr),
}


async def facets(session: AsyncSession, filters: CorpusFilters | None = None) -> dict[str, Any]:
    """Per-value counts for every Browse facet.

    Each facet is counted with every *other* filter applied (its own selection
    cleared), so unchecked values still show how many rows they would add.
    """
    flt = filters or CorpusFilters()
    out: dict[str, list[dict[str, Any]]] = {}
    for name, (cleared_fields, expr_factory) in _FACETS.items():
        expr = expr_factory().label("value")
        stmt = apply_filters(
            select(expr, func.count(Clause.id)), replace(flt, **cleared_fields)
        ).group_by(literal_column("value"))
        counts = {value: int(n) for value, n in (await session.execute(stmt)).all()}
        out[name] = _ordered_counts(name, counts)
    return out


def _ordered_counts(name: str, counts: dict[Any, int]) -> list[dict[str, Any]]:
    fixed: tuple[str, ...] | None = {
        "fact_check": FACT_CHECK_STATUSES,
        "quality": QUALITY_VALUES,
        "length": tuple(label for label, _, _ in LENGTH_BUCKETS),
    }.get(name)
    if fixed is not None:
        return [{"value": v, "count": counts.get(v, 0)} for v in fixed]
    items = [{"value": v, "count": n} for v, n in counts.items()]
    return sorted(items, key=lambda i: (-i["count"], str(i["value"])))


# ---------------------------------------------------------------------------
# Detail + neighbors
# ---------------------------------------------------------------------------


def entities_from(tokens: Any, groups: Any) -> list[dict[str, str]]:
    """Entity-like spans from stored spaCy features.

    Noun chunks (labelled by their root token's POS) plus proper-noun tokens not
    already covered. Stored features carry no NER labels, so ``PROPN`` / ``NOUN``
    stand in for the entity type.
    """
    token_list = tokens if isinstance(tokens, list) else []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    noun_chunks = groups.get("noun_chunks", []) if isinstance(groups, dict) else []
    for nc in noun_chunks:
        text = str(nc.get("text", "")).strip()
        if not text or text.lower() in seen:
            continue
        root = nc.get("root")
        label = "NOUN"
        if isinstance(root, int) and 0 <= root < len(token_list):
            label = str(token_list[root].get("pos") or "NOUN")
        seen.add(text.lower())
        out.append({"text": text, "label": label})
    for tok in token_list:
        if isinstance(tok, dict) and tok.get("pos") == "PROPN":
            text = str(tok.get("text", "")).strip()
            if text and not any(text.lower() in s for s in seen):
                seen.add(text.lower())
                out.append({"text": text, "label": "PROPN"})
    return out


async def _latest_fact_check(session: AsyncSession, external_id: str) -> dict[str, Any] | None:
    stmt = (
        select(FactCheck)
        .where(FactCheck.clause_external_id == external_id)
        .order_by(FactCheck.id.desc())
        .limit(1)
    )
    fc = (await session.execute(stmt)).scalar_one_or_none()
    if fc is None:
        return None
    return {
        "id": fc.id,
        "verdict": fc.verdict,
        "confidence": fc.confidence,
        "probabilities": fc.probabilities,
        "sift_steps": fc.sift_steps,
        "citations": fc.citations,
        "trace_id": fc.trace_id,
        "model": fc.model,
        "latency_ms": fc.latency_ms,
        "job_id": fc.job_id,
        "created_at": fc.created_at.isoformat() if fc.created_at else None,
    }


async def context_lines(
    session: AsyncSession, clause: Clause, before: int = CONTEXT_LINES, after: int = CONTEXT_LINES
) -> dict[str, list[dict[str, Any]]]:
    """The ``before``/``after`` neighbouring children of the same run by ``sentence_index``."""
    if clause.sentence_index is None or clause.run_id is None:
        return {"before": [], "after": []}
    idx = clause.sentence_index
    stmt = (
        select(Clause.external_id, Clause.sentence_index, Clause.text)
        .where(
            Clause.run_id == clause.run_id,
            Clause.sentence_index >= idx - before,
            Clause.sentence_index <= idx + after,
            Clause.sentence_index != idx,
        )
        .order_by(Clause.sentence_index)
    )
    rows = [
        {"external_id": e, "sentence_index": i, "text": t}
        for e, i, t in (await session.execute(stmt)).all()
    ]
    return {
        "before": [r for r in rows if r["sentence_index"] < idx],
        "after": [r for r in rows if r["sentence_index"] > idx],
    }


async def chunk_detail(session: AsyncSession, external_id: str) -> dict[str, Any]:
    """Everything the detail pane shows for one chunk.

    Raises :class:`ChunkNotFoundError` when the id is unknown.
    """
    fc_status = _fact_check_expr().label("fc")
    stmt = (
        select(Clause, ChunkRun, ParentChunk, Topic.label, fc_status)
        .join(ChunkRun, ChunkRun.id == Clause.run_id, isouter=True)
        .join(ParentChunk, ParentChunk.id == Clause.parent_id, isouter=True)
        .join(Topic, Topic.id == Clause.topic_id, isouter=True)
        .where(Clause.external_id == external_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        raise ChunkNotFoundError(external_id)
    clause, run, parent, topic_label, status = row
    detail = _row(clause, run, status)

    parent_info = None
    if parent is not None:
        start = parent.text.find(clause.text)
        n_children = int(
            (
                await session.execute(
                    select(func.count(Clause.id)).where(Clause.parent_id == parent.id)
                )
            ).scalar_one()
        )
        parent_info = {
            "id": parent.id,
            "index": parent.index,
            "text": parent.text,
            "char_start": parent.char_start,
            "char_end": parent.char_end,
            "child_start": start if start >= 0 else None,
            "child_end": start + len(clause.text) if start >= 0 else None,
            "n_children": n_children,
        }
    n_parents = run.n_parents if run else None
    detail.update(
        {
            "parent": parent_info,
            "n_parents": n_parents,
            "context": await context_lines(session, clause),
            "entities": entities_from(clause.tokens, clause.groups),
            "sfl": format_sfl(clause.sfl) if clause.sfl is not None else None,
            "sfl_raw": clause.sfl,
            "tokens": clause.tokens,
            "groups": clause.groups,
            "topic": topic_label,
            "latest_fact_check": await _latest_fact_check(session, external_id),
            "run": (
                {
                    "id": run.id,
                    "strategy": run.strategy,
                    "chunker_version": run.chunker_version,
                    "is_active": run.is_active,
                    "trace_id": run.trace_id,
                    "source_hash": run.source_hash,
                    "params": run.params,
                    "created_at": run.created_at.isoformat() if run.created_at else None,
                }
                if run
                else None
            ),
            "created_at": clause.created_at.isoformat() if clause.created_at else None,
        }
    )
    return detail


async def neighbors(
    session: AsyncSession,
    external_id: str,
    k: int = 10,
    *,
    near_dup_threshold: float = NEAR_DUP_L2,
) -> list[dict[str, Any]]:
    """Nearest chunks by L2 distance from the clause's *stored* embedding.

    No re-embedding. Other runs of the same document are skipped (they are
    copies of this chunk). Each neighbor is flagged ``near_duplicate`` when its
    distance is under ``near_dup_threshold``.
    """
    me = (
        await session.execute(
            select(Clause.document_id, Clause.run_id, Embedding.embedding)
            .join(Embedding, Embedding.clause_id == Clause.external_id)
            .where(Clause.external_id == external_id)
            .limit(1)
        )
    ).first()
    if me is None:
        exists_row = (
            await session.execute(select(Clause.id).where(Clause.external_id == external_id))
        ).first()
        if exists_row is None:
            raise ChunkNotFoundError(external_id)
        return []
    document_id, run_id, vector = me
    distance = Embedding.embedding.l2_distance(vector)
    same_doc_other_run = and_(
        Clause.document_id == document_id, Clause.run_id.is_distinct_from(run_id)
    )
    stmt = (
        select(Clause, ChunkRun, distance.label("distance"))
        .join(Embedding, Embedding.clause_id == Clause.external_id)
        .join(ChunkRun, ChunkRun.id == Clause.run_id, isouter=True)
        .where(Clause.external_id != external_id, ~same_doc_other_run)
        .order_by(distance)
        .limit(k)
    )
    out = []
    for clause, run, dist in (await session.execute(stmt)).all():
        row = _row(clause, run, "unchecked")
        row.pop("fact_check")
        row["distance"] = float(dist)
        row["near_duplicate"] = float(dist) < near_dup_threshold
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# Runs, stats, health
# ---------------------------------------------------------------------------


def run_dict(run: ChunkRun) -> dict[str, Any]:
    params = run.params or {}
    return {
        "id": run.id,
        "document_id": run.document_id,
        "notebook_id": run.notebook_id,
        "strategy": run.strategy,
        "chunker_version": run.chunker_version,
        "kind": params.get("kind", "source"),
        "title": params.get("title"),
        "params": params,
        "n_parents": run.n_parents,
        "n_children": run.n_children,
        "mean_len": run.mean_len,
        "p95_len": run.p95_len,
        "entity_vetoes": run.entity_vetoes,
        "is_active": run.is_active,
        "source_hash": run.source_hash,
        "trace_id": run.trace_id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


async def runs(
    session: AsyncSession,
    *,
    notebook_id: str | None = None,
    document_id: str | None = None,
    active_only: bool = False,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    """``chunk_runs`` newest first, optionally narrowed."""
    stmt = select(ChunkRun)
    if notebook_id is not None:
        stmt = stmt.where(ChunkRun.notebook_id == notebook_id)
    if document_id is not None:
        stmt = stmt.where(ChunkRun.document_id == document_id)
    if active_only:
        stmt = stmt.where(ChunkRun.is_active.is_(True))
    stmt = stmt.order_by(ChunkRun.id.desc()).limit(limit)
    return [run_dict(r) for r in (await session.execute(stmt)).scalars()]


async def stats(session: AsyncSession, filters: CorpusFilters | None = None) -> dict[str, Any]:
    """Corpus counts plus ``max_clause_id`` (drives the "N new chunks" pill)."""
    flt = filters or CorpusFilters()
    base = apply_filters(
        select(
            func.count(Clause.id),
            func.count(func.distinct(Clause.parent_id)),
            func.count(func.distinct(Clause.document_id)),
            func.count(func.distinct(Clause.run_id)),
            func.max(Clause.id),
        ),
        flt,
    )
    n_clauses, n_parents, n_docs, n_runs, max_id = (await session.execute(base)).one()
    totals = (
        await session.execute(
            select(
                select(func.count(ChunkRun.id)).scalar_subquery(),
                select(func.count(Embedding.id)).scalar_subquery(),
                select(func.count(FactCheck.id)).scalar_subquery(),
                select(func.max(Clause.id)).scalar_subquery(),
            )
        )
    ).one()
    return {
        "clauses": int(n_clauses),
        "parents": int(n_parents),
        "documents": int(n_docs),
        "runs": int(n_runs),
        "all_runs": int(totals[0]),
        "embeddings": int(totals[1]),
        "fact_checks": int(totals[2]),
        "max_clause_id": int(totals[3] or 0),
        "filtered_max_clause_id": int(max_id or 0),
    }


async def count_new_since(
    session: AsyncSession, since_id: int, filters: CorpusFilters | None = None
) -> int:
    """How many matching clauses have ``id > since_id``."""
    stmt = apply_filters(select(func.count(Clause.id)), filters or CorpusFilters()).where(
        Clause.id > since_id
    )
    return int((await session.execute(stmt)).scalar_one())


async def embedder_health(timeout: float = 2.0) -> dict[str, Any]:
    """Probe the Ollama embedder (``GET /api/tags``). Never raises."""
    base_url = os.environ.get("OLLAMA_URL", DEFAULT_OLLAMA_URL)
    model = os.environ.get("EMBEDDING_MODEL", DEFAULT_OLLAMA_MODEL)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/api/tags")
        ok = resp.status_code == 200
        models = [m.get("name") for m in resp.json().get("models", [])] if ok else []
        return {
            "ok": ok,
            "url": base_url,
            "model": model,
            "model_present": any(str(m).startswith(model.split(":")[0]) for m in models),
        }
    except Exception as e:  # noqa: BLE001 - health probe must not raise
        return {"ok": False, "url": base_url, "model": model, "error": type(e).__name__}


# ---------------------------------------------------------------------------
# Map
# ---------------------------------------------------------------------------


#: ``(clause_count, max_clause_id, method)`` -> projected points.
_MAP_CACHE: dict[tuple[int, int, str], list[dict[str, Any]]] = {}


def _project(vectors: Any, method: str) -> Any:
    import numpy as np

    data = np.asarray(vectors, dtype=np.float32)
    if len(data) == 0:
        return np.zeros((0, 2), dtype=np.float32)
    if method == "umap" and len(data) >= 15:
        try:
            import umap

            reducer = umap.UMAP(n_components=2, random_state=42, metric="cosine")
            return reducer.fit_transform(data)
        except Exception as e:  # noqa: BLE001 - UMAP is optional; PCA always works
            logger.info("UMAP unavailable (%s); falling back to PCA", e)
    centered = data - data.mean(axis=0)
    if len(data) == 1:
        return np.zeros((1, 2), dtype=np.float32)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    comps = vt[:2]
    projected = centered @ comps.T
    if projected.shape[1] < 2:
        projected = np.hstack([projected, np.zeros((len(projected), 1), dtype=np.float32)])
    return projected


async def map_points(
    session: AsyncSession,
    *,
    method: str = "pca",
    filters: CorpusFilters | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """2D projection of active-chunk embeddings, colored by topic or document.

    Cached by ``(clause_count, max_clause_id, method)`` for the unfiltered map.
    """
    flt = filters or CorpusFilters()
    stmt = apply_filters(
        select(
            Clause.external_id,
            Clause.document_id,
            Clause.text,
            Topic.label,
            Embedding.embedding,
        )
        .join(Embedding, Embedding.clause_id == Clause.external_id)
        .join(Topic, Topic.id == Clause.topic_id, isouter=True),
        flt,
    ).order_by(Clause.id)
    rows = (await session.execute(stmt)).all()
    has_topics = any(r[3] for r in rows)
    key: tuple[int, int, str] | None = None
    if use_cache and flt == CorpusFilters():
        s = await stats(session)
        key = (s["clauses"], s["max_clause_id"], method)
        if key in _MAP_CACHE:
            return {"points": _MAP_CACHE[key], "color_by": "topic" if has_topics else "document"}
    coords = await asyncio.to_thread(_project, [r[4] for r in rows], method)
    points = [
        {
            "x": float(coords[i][0]),
            "y": float(coords[i][1]),
            "external_id": r[0],
            "document_id": r[1],
            "preview": r[2][:140],
            "topic": r[3],
        }
        for i, r in enumerate(rows)
    ]
    if key is not None:
        _MAP_CACHE.clear()
        _MAP_CACHE[key] = points
    return {"points": points, "color_by": "topic" if has_topics else "document"}
