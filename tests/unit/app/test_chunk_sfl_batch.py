"""Chunk SFL in the assessment loops uses the configured (batching) engine."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from notebooklm._app import assessment, sfl_tagging


class BatchEngine:
    batch = True

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.batches: list[list[str]] = []

    def forward_batch(self, texts: list[str]) -> list[Any]:
        self.batches.append(list(texts))
        if self.fail:
            raise RuntimeError("agent down")
        return [{"ideational": {}, "interpersonal": {"tenor": "casual"}} for _ in texts]

    def __call__(self, utterance: str) -> dict[str, Any]:
        return {"ideational": {}, "interpersonal": {"tenor": "neutral"}}


class PerUtteranceEngine:
    def __call__(self, utterance: str) -> dict[str, Any]:
        raise AssertionError("must not be called up front")


def test_batching_engine_annotates_all_chunks_in_one_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = BatchEngine()
    monkeypatch.setattr(sfl_tagging, "default_engine", lambda: engine)
    messages: list[str] = []
    got, batch = asyncio.run(assessment._prepare_chunk_sfl(["a", "b", "c"], messages.append))
    assert got is engine
    assert engine.batches == [["a", "b", "c"]]
    assert batch is not None and len(batch) == 3
    assert messages == ["Running SFL over 3 chunks..."]


def test_non_batching_engine_keeps_per_chunk_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = PerUtteranceEngine()
    monkeypatch.setattr(sfl_tagging, "default_engine", lambda: engine)
    got, batch = asyncio.run(assessment._prepare_chunk_sfl(["a"]))
    assert got is engine and batch is None


def test_failed_batch_falls_back_to_per_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = BatchEngine(fail=True)
    monkeypatch.setattr(sfl_tagging, "default_engine", lambda: engine)
    got, batch = asyncio.run(assessment._prepare_chunk_sfl(["a", "b"]))
    assert got is engine and batch is None
