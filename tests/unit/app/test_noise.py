"""Noise detector: Python twin and the SQL expression agree (fact-17)."""

from __future__ import annotations

import pytest
from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from notebooklm._app.noise import classify_noise, noise_sql
from tests._fixtures.postgres import pg_session  # noqa: F401

SAMPLES = {
    "": None,
    "The kernel panics when the cgroup memory limit is hit.": None,
    "NsMvbzsVTlHfstpSeMH70+Qn0nTeo4OkzXKd/43HBfE1ksw//KH7RVvrc1xYsVF/4iken9nTH+Nwu": "base64",
    "data: iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==": "base64",
    "0.273 0.327 0.307 0.404 0.337 0.410 0.373 0.428 Recite 0.215 0.318 0.209": "numeric_table",
    "Table 3 shows 12 results across 4 runs": None,
    "1 2 3 4 5": None,  # too few tokens
    "Supercalifragilisticexpialidocious is a long word without digits": None,
    "-1 +2 3.5 40% 12,5 .7 x": "numeric_table",
}


@pytest.mark.parametrize(("text", "expected"), list(SAMPLES.items()))
def test_classify_noise(text: str, expected: str | None) -> None:
    assert classify_noise(text) == expected


@pytest.mark.asyncio
async def test_sql_twin_matches_python(pg_session: AsyncSession) -> None:  # noqa: F811
    for text, expected in SAMPLES.items():
        expr = noise_sql("t.text")
        stmt = select(expr).select_from(select(literal(text).label("text")).subquery("t"))
        got = (await pg_session.execute(stmt)).scalar_one()
        assert got == (expected or "clean"), text
