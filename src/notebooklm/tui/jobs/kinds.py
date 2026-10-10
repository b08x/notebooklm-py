"""Job kind registry.

Each kind's handler lives in its own module ``handlers/<kind>.py`` exposing
``async def handle(ctx: JobContext) -> str | None``. Modules are imported lazily
so heavy dependencies (spaCy, BERTopic, DSPy) load only when a job of that kind
runs.
"""

from __future__ import annotations

import importlib

from .runner import Handler

JOB_KINDS: tuple[str, ...] = (
    "download",
    "ingest",
    "sfl_tag",
    "fact_check",
    "compile",
    "generate",
    "topic_model",
)


def resolve_handler(kind: str) -> Handler:
    if kind not in JOB_KINDS:
        raise KeyError(f"Unknown job kind {kind!r}")
    module = importlib.import_module(f"{__package__}.handlers.{kind}")
    handler: Handler = module.handle
    return handler
