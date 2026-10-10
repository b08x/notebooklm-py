from __future__ import annotations

from notebooklm.db.models import FACT_CHECK_VERDICTS, Base


def _fk_targets(table) -> dict[str, str]:
    return {fk.parent.name: fk.target_fullname for fk in table.foreign_keys}


def test_new_tables_exist() -> None:
    for name in ("chunk_runs", "parent_chunks", "fact_checks", "topic_runs", "topics"):
        assert name in Base.metadata.tables


def test_clauses_link_to_run_parent_topic() -> None:
    clauses = Base.metadata.tables["clauses"]
    for col in ("run_id", "parent_id", "sfl", "topic_id", "tokens", "groups"):
        assert col in clauses.c
    assert _fk_targets(clauses) == {
        "run_id": "chunk_runs.id",
        "parent_id": "parent_chunks.id",
        "topic_id": "topics.id",
    }


def test_chunk_runs_provenance_columns() -> None:
    cols = set(Base.metadata.tables["chunk_runs"].c.keys())
    assert {
        "strategy",
        "params",
        "chunker_version",
        "source_hash",
        "trace_id",
        "n_parents",
        "n_children",
        "mean_len",
        "p95_len",
        "entity_vetoes",
        "is_active",
    } <= cols


def test_fact_checks_columns_and_verdicts() -> None:
    fc = Base.metadata.tables["fact_checks"]
    assert {
        "clause_external_id",
        "job_id",
        "verdict",
        "confidence",
        "probabilities",
        "sift_steps",
        "citations",
        "trace_id",
        "model",
        "latency_ms",
    } <= set(fc.c.keys())
    assert set(fc.c.verdict.type.enums) == set(FACT_CHECK_VERDICTS)
    assert _fk_targets(fc) == {"clause_external_id": "clauses.external_id"}
