"""Noise detector for chunks: base64/binary blobs and numeric-table rows.

Two implementations of one rule set:

* :func:`noise_sql` — a SQL ``CASE`` expression over ``clauses.text`` so Browse
  facets and filters run inside Postgres;
* :func:`classify_noise` — the Python twin used by unit tests and by callers
  that already hold the text.

Rules (``base64`` wins when both match):

* **base64** — runs of 24+ base64-alphabet characters (``[A-Za-z0-9+/=]``)
  make up more than half the text, and the text holds at least one digit and
  one uppercase letter (plain long words never qualify).
* **numeric_table** — at least 6 whitespace-separated tokens, and 60% or more
  of them are numbers (``-1``, ``0.273``, ``12,5``, ``40%``).
"""

from __future__ import annotations

import re
from typing import Literal

from sqlalchemy import ColumnElement, literal_column

NoiseKind = Literal["base64", "numeric_table"]

#: Values of the Browse "quality" facet.
QUALITY_VALUES = ("clean", "base64", "numeric_table")

BASE64_RUN = r"[A-Za-z0-9+/=]{24,}"
NUMERIC_TOKEN = r"^[-+]?[0-9]*[.,]?[0-9]+%?$"
MIN_TABLE_TOKENS = 6
NUMERIC_RATIO = 0.6

_BASE64_RUN_RE = re.compile(BASE64_RUN)
_NUMERIC_TOKEN_RE = re.compile(NUMERIC_TOKEN)


def classify_noise(text: str) -> NoiseKind | None:
    """Return ``"base64"``, ``"numeric_table"`` or ``None`` for clean text."""
    if not text:
        return None
    stripped = _BASE64_RUN_RE.sub("", text)
    if len(stripped) * 2 < len(text) and re.search(r"[0-9]", text) and re.search(r"[A-Z]", text):
        return "base64"
    tokens = text.split()
    if len(tokens) >= MIN_TABLE_TOKENS:
        numeric = sum(1 for tok in tokens if _NUMERIC_TOKEN_RE.match(tok))
        if numeric >= NUMERIC_RATIO * len(tokens):
            return "numeric_table"
    return None


def noise_sql(column: str = "clauses.text") -> ColumnElement[str]:
    """SQL twin of :func:`classify_noise`: ``'base64' | 'numeric_table' | 'clean'``."""
    tokens = f"regexp_split_to_array(btrim({column}), '\\s+')"
    numeric = f"(SELECT count(*) FROM unnest({tokens}) AS tok WHERE tok ~ '{NUMERIC_TOKEN}')"
    sql = (
        "CASE"
        f" WHEN length(regexp_replace({column}, '{BASE64_RUN}', '', 'g')) * 2 < length({column})"
        f" AND {column} ~ '[0-9]' AND {column} ~ '[A-Z]' THEN 'base64'"
        f" WHEN coalesce(array_length({tokens}, 1), 0) >= {MIN_TABLE_TOKENS}"
        f" AND {numeric} >= {NUMERIC_RATIO} * array_length({tokens}, 1) THEN 'numeric_table'"
        " ELSE 'clean' END"
    )
    return literal_column(sql)
