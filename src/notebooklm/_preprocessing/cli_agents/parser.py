"""Extract a JSON payload from free-form CLI agent output.

Agents are asked for bare JSON but routinely wrap it in markdown fences, prefix
it with a sentence, emit ANSI colour codes, or return near-JSON (trailing
commas, smart quotes, Python literals, a truncated closing bracket). This module
recovers the payload in that order of escalation and raises
:class:`JSONExtractionError` when nothing parses.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_FENCE = re.compile(r"```[ \t]*(?:json|JSON|javascript|js)?[ \t]*\n?(.*?)```", re.DOTALL)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


class JSONExtractionError(ValueError):
    """No JSON value could be recovered from the text."""


def _loads(text: str) -> tuple[bool, Any]:
    try:
        return True, json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return False, None


def _scan(text: str) -> tuple[bool, Any, int]:
    """Decode the ``{``/``[`` position that yields the longest complete JSON value.

    Prefers the longest value so a stray ``[note]`` in a preamble does not
    shadow the real object that follows it. Returns ``(ok, value, start)``.
    """
    decoder = json.JSONDecoder()
    best: tuple[int, Any, int] | None = None
    for match in re.finditer(r"[\[{]", text):
        try:
            value, end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        length = end - match.start()
        if best is None or length > best[0]:
            best = (length, value, match.start())
    return (True, best[1], best[2]) if best is not None else (False, None, -1)


def _first_opener(text: str) -> int:
    return min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)


def _close_brackets(text: str) -> str:
    """Append the closers a truncated JSON document is missing."""
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append("]" if ch == "[" else "}")
        elif ch in "]}" and stack:
            stack.pop()
    suffix = '"' if in_string else ""
    return text + suffix + "".join(reversed(stack))


def _repair(text: str) -> tuple[bool, Any]:
    """Fix near-JSON starting at the outermost opener.

    Whole-document fixes run before inner-fragment scanning, so a truncated
    batch is closed and kept intact rather than reduced to its first item.
    """
    start = _first_opener(text)
    if start < 0:
        return False, None
    candidate = _TRAILING_COMMA.sub(r"\1", text[start:].translate(_SMART_QUOTES).strip())
    attempts = [candidate, _TRAILING_COMMA.sub(r"\1", _close_brackets(candidate))]
    for attempt in attempts:
        ok, value = _loads(attempt)
        if ok:
            return True, value
    for attempt in attempts:
        try:
            value = ast.literal_eval(attempt)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            continue
        if isinstance(value, (dict, list)):
            return True, value
    for attempt in attempts:
        ok, value, _ = _scan(attempt)
        if ok:
            return True, value
    return False, None


def extract_and_repair_json(text: str) -> Any:
    """Return the JSON value embedded in ``text``.

    Raises :class:`JSONExtractionError` when no strategy recovers a value.
    """
    if not isinstance(text, str):
        raise JSONExtractionError(f"expected str, got {type(text).__name__}")
    cleaned = _ANSI.sub("", text).strip()
    if not cleaned:
        raise JSONExtractionError("empty output")

    ok, value = _loads(cleaned)
    if ok:
        return value
    for block in _FENCE.findall(cleaned):
        ok, value = _loads(block.strip())
        if ok:
            return value
    for block in _FENCE.findall(cleaned):
        ok, value = _repair(block)
        if ok:
            return value
    ok, value, start = _scan(cleaned)
    if ok and start == _first_opener(cleaned):
        return value
    ok, value = _repair(cleaned)
    if ok:
        return value
    preview = cleaned[:120].replace("\n", " ")
    raise JSONExtractionError(f"no JSON found in agent output: {preview!r}")
