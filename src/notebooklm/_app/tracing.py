"""Root OpenTelemetry spans for TUI jobs.

Each job runs inside one ``job.<kind>`` span so every DSPy call it makes (via the
openinference instrumentor installed by ``setup_dspy_router``) nests under a
single Langfuse trace. The trace id is persisted on the job record, the
``chunk_runs`` row, and every ``fact_checks`` row so stored results link back to
the trace that produced them.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import trace

_TRACER_NAME = "notebooklm.jobs"
DEFAULT_LANGFUSE_HOST = "http://tinybot:3000"


def current_trace_id() -> str | None:
    """Hex trace id of the active span, or ``None`` when tracing is not recording."""
    ctx = trace.get_current_span().get_span_context()
    if not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


@contextmanager
def job_span(kind: str, **attributes: Any) -> Iterator[str | None]:
    """Open the root span ``job.<kind>`` and yield its trace id.

    Yields ``None`` when no tracer provider is installed (Langfuse keys unset),
    so callers store a NULL trace id instead of a meaningless all-zero one.
    """
    tracer = trace.get_tracer(_TRACER_NAME)
    attrs = {k: str(v) for k, v in attributes.items() if v is not None}
    with tracer.start_as_current_span(f"job.{kind}", attributes=attrs):
        yield current_trace_id()


def trace_url(trace_id: str | None) -> str | None:
    """Langfuse UI URL for ``trace_id``, or ``None`` when there is no trace."""
    if not trace_id:
        return None
    host = (
        os.environ.get("LANGFUSE_HOST")
        or os.environ.get("LANGFUSE_BASE_URL")
        or DEFAULT_LANGFUSE_HOST
    ).rstrip("/")
    return f"{host}/trace/{trace_id}"
