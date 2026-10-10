"""Live-Postgres session fixture, rolled back after each test.

Import it into a test module (``from tests._fixtures.postgres import pg_session``).
Tests using it FAIL, never skip, when Postgres is unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from notebooklm.db.session import DATABASE_URL


@pytest_asyncio.fixture
async def pg_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        conn = await engine.connect()
    except Exception as e:  # pragma: no cover - environment failure path
        await engine.dispose()
        pytest.fail(f"Postgres unreachable at {DATABASE_URL}: {e}", pytrace=False)
    trans = await conn.begin()
    session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        await session.close()
        await trans.rollback()
        await conn.close()
        await engine.dispose()
