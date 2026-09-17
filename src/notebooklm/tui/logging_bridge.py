"""Routes application log records into the TUI's in-memory Logs view.

``run_tui`` renders a full-screen ``rich.Live`` display — any log record that
reaches a ``StreamHandler`` writing to stdout/stderr corrupts that screen. The
previous fix was to raise every logger's level to ``ERROR``, which also
suppressed the very information needed to diagnose a background failure (e.g.
an Ollama embedding timeout during ingestion). This module instead redirects
records into a bounded in-memory buffer (``TUIState.log_records``) rendered by
the Logs view (``keypress`` toggles it with ``L``), so nothing is lost.
"""

from __future__ import annotations

import logging
from collections import deque

DEFAULT_TUI_LOG_LEVEL = "INFO"


class TUILogHandler(logging.Handler):
    """Appends formatted records to a bounded deque instead of writing anywhere."""

    def __init__(self, buffer: deque):
        super().__init__()
        self.buffer = buffer
        self.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S"
            )
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.buffer.append((record.levelname, self.format(record)))
        except Exception:
            # A logging handler must never itself raise into application code.
            self.handleError(record)


def install_tui_log_handler(buffer: deque, level: str | None = None) -> None:
    """Mute stdout/stderr-writing handlers and route all logging into ``buffer``.

    Attaches a single :class:`TUILogHandler` to the root logger only — the
    ``notebooklm`` logger propagates to root, so attaching there too would
    double every ``notebooklm.*`` record. Any handler already attached
    anywhere (e.g. the ``notebooklm`` logger's default ``StreamHandler`` from
    ``configure_logging()``) is muted by raising its level rather than
    removed, so it resumes working unmodified if the TUI exits or a caller
    re-raises the level later.

    ``level`` defaults to ``NOTEBOOKLM_TUI_LOG_LEVEL`` env, then ``INFO`` —
    verbose enough to see what an ingestion/embedding call is doing without
    the DEBUG-level SQL/HTTP noise from every dependency by default.
    """
    import os

    resolved_level = level or os.environ.get("NOTEBOOKLM_TUI_LOG_LEVEL", DEFAULT_TUI_LOG_LEVEL)
    level_no = getattr(logging, resolved_level.upper(), logging.INFO)

    for logger_name in (None, "notebooklm"):
        target = logging.getLogger(logger_name)
        for existing in list(target.handlers):
            existing.setLevel(logging.CRITICAL + 1)
        target.setLevel(level_no)

    handler = TUILogHandler(buffer)
    handler.setLevel(level_no)
    logging.getLogger().addHandler(handler)
