"""Traced background jobs: one Langfuse trace + structured logs (QA facts 16-18)."""

from __future__ import annotations

import asyncio
import logging
import re

import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from notebooklm._app import tracing
from notebooklm._app.background import JobRegistry


class Engine:
    """A fake SFL engine that opens one span per forward call (like DSPy's instrumentor)."""

    def forward(self, text: str) -> dict[str, object]:
        tracer = tracing.trace.get_tracer("test")
        with tracer.start_as_current_span("engine.forward"):
            return {"ideational": {}, "interpersonal": {"mood": "declarative"}}


@pytest.fixture
def spans(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing.trace, "get_tracer", provider.get_tracer)
    return exporter


def test_traced_sfl_job_has_one_root_span_and_logged_lines(spans, caplog) -> None:
    registry = JobRegistry()

    async def body(job) -> dict[str, object]:  # noqa: ANN001 - BackgroundJob
        job.progress("tagging clause 1/1", 0, 1)
        Engine().forward("Water boils.")
        job.progress("tagging clause 1/1", 1, 1)
        return {"tagged": 1, "failed": 0}

    async def go() -> None:
        job = registry.start("sfl_tag", "SFL tag test", body, traced=True)
        await job._task
        return job

    with caplog.at_level(logging.INFO, logger="notebooklm._app.background"):
        job = asyncio.run(go())

    finished = [s for s in spans.get_finished_spans() if s.name == "job.sfl_tag"]
    assert len(finished) == 1
    engine_spans = [s for s in spans.get_finished_spans() if s.name == "engine.forward"]
    assert len(engine_spans) == 1
    assert engine_spans[0].parent.span_id == finished[0].context.span_id  # nested under the job
    assert engine_spans[0].context.trace_id == finished[0].context.trace_id

    snapshot = job.snapshot()
    assert snapshot["status"] == "done"
    assert re.fullmatch(r"[0-9a-f]{32}", job.trace_id or "")
    assert snapshot["trace_url"] is not None and snapshot["trace_url"].endswith(job.trace_id)
    assert snapshot["started_at"] is not None and snapshot["finished_at"] is not None

    lines = [r.message for r in caplog.records if "job_id=" in r.message]
    assert any(f"job_id={job.id}" in m and "started" in m for m in lines)
    assert any(f"job_id={job.id}" in m and "done" in m for m in lines)


def test_failing_traced_job_logs_error_with_job_id(spans, caplog) -> None:
    registry = JobRegistry()

    async def body(job) -> None:  # noqa: ANN001 - BackgroundJob
        raise RuntimeError("boom")

    async def go() -> None:
        job = registry.start("sfl_tag", "SFL tag bad", body, traced=True)
        await job._task
        return job

    with caplog.at_level(logging.INFO, logger="notebooklm._app.background"):
        job = asyncio.run(go())

    assert job.snapshot()["status"] == "failed"
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1 and f"job_id={job.id}" in errors[0].message
    assert "RuntimeError: boom" in errors[0].message


def test_untraced_job_has_no_trace_url() -> None:
    registry = JobRegistry()

    async def body(job) -> int:  # noqa: ANN001 - BackgroundJob
        return 1

    async def go() -> None:
        job = registry.start("ingest", "ingest x", body)
        await job._task
        return job

    job = asyncio.run(go())
    assert job.snapshot()["status"] == "done"
    assert job.trace_id is None and job.snapshot()["trace_url"] is None
