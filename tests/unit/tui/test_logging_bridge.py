"""Unit tests for the TUI's in-memory log capture (``tui/logging_bridge.py``)."""

from __future__ import annotations

import logging
from collections import deque

from notebooklm.tui.logging_bridge import TUILogHandler, install_tui_log_handler


def _make_record(name: str, level: int, message: str) -> logging.LogRecord:
    return logging.getLogger(name).makeRecord(name, level, __file__, 0, message, (), None)


def test_tui_log_handler_appends_formatted_level_and_message():
    buffer: deque = deque(maxlen=10)
    handler = TUILogHandler(buffer)

    handler.emit(_make_record("notebooklm._preprocessing.embeddings", logging.WARNING, "timed out"))

    assert len(buffer) == 1
    level, line = buffer[0]
    assert level == "WARNING"
    assert "timed out" in line
    assert "notebooklm._preprocessing.embeddings" in line


def test_tui_log_handler_respects_buffer_maxlen():
    buffer: deque = deque(maxlen=2)
    handler = TUILogHandler(buffer)

    for i in range(5):
        handler.emit(_make_record("notebooklm", logging.INFO, f"msg {i}"))

    assert len(buffer) == 2
    assert "msg 3" in buffer[0][1]
    assert "msg 4" in buffer[1][1]


def test_install_tui_log_handler_captures_notebooklm_records(monkeypatch):
    monkeypatch.delenv("NOTEBOOKLM_TUI_LOG_LEVEL", raising=False)
    buffer: deque = deque(maxlen=50)
    nb_logger = logging.getLogger("notebooklm")
    root_logger = logging.getLogger()
    original_nb_level = nb_logger.level
    original_root_level = root_logger.level
    installed_handlers = list(root_logger.handlers)

    try:
        install_tui_log_handler(buffer)
        nb_logger.warning("ollama embedding request timed out")

        assert any("ollama embedding request timed out" in line for _, line in buffer)
    finally:
        # Undo the install so this test doesn't leak handlers into the rest
        # of the suite (root logger is process-global).
        for h in list(root_logger.handlers):
            if h not in installed_handlers:
                root_logger.removeHandler(h)
        nb_logger.setLevel(original_nb_level)
        root_logger.setLevel(original_root_level)


def test_install_tui_log_handler_honors_env_level(monkeypatch):
    monkeypatch.setenv("NOTEBOOKLM_TUI_LOG_LEVEL", "ERROR")
    buffer: deque = deque(maxlen=50)
    nb_logger = logging.getLogger("notebooklm")
    root_logger = logging.getLogger()
    original_nb_level = nb_logger.level
    original_root_level = root_logger.level
    installed_handlers = list(root_logger.handlers)

    try:
        install_tui_log_handler(buffer)
        nb_logger.info("should be filtered out at ERROR level")
        nb_logger.error("should come through")

        lines = [line for _, line in buffer]
        assert not any("should be filtered out" in line for line in lines)
        assert any("should come through" in line for line in lines)
    finally:
        for h in list(root_logger.handlers):
            if h not in installed_handlers:
                root_logger.removeHandler(h)
        nb_logger.setLevel(original_nb_level)
        root_logger.setLevel(original_root_level)
