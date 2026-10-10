from __future__ import annotations

import re

from opentelemetry.sdk.trace import TracerProvider

from notebooklm._app import tracing


def test_job_span_yields_none_without_provider() -> None:
    with tracing.job_span("download", job_id="j1") as trace_id:
        assert trace_id is None or re.fullmatch(r"[0-9a-f]{32}", trace_id)


def test_job_span_yields_hex_trace_id_with_provider(monkeypatch) -> None:
    provider = TracerProvider()
    monkeypatch.setattr(tracing.trace, "get_tracer", provider.get_tracer)
    with tracing.job_span("ingest", job_id="j1", notebook_id=None) as trace_id:
        assert trace_id is not None and re.fullmatch(r"[0-9a-f]{32}", trace_id)
        assert tracing.current_trace_id() == trace_id


def test_trace_url(monkeypatch) -> None:
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    assert tracing.trace_url(None) is None
    assert tracing.trace_url("ab" * 16) == f"http://tinybot:3000/trace/{'ab' * 16}"
    monkeypatch.setenv("LANGFUSE_HOST", "http://lf:3000/")
    assert tracing.trace_url("x") == "http://lf:3000/trace/x"
