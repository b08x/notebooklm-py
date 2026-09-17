import os
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    # Matches deploy/docker-compose.db.yml's default host port (5435, not
    # Postgres's usual 5432 — chosen to avoid colliding with unrelated local
    # Postgres instances).
    "postgresql+asyncpg://postgres:postgres@localhost:5435/notebooklm",
)

# ``poolclass=NullPool``: this module-level ``engine`` is imported once and
# reused across every TUI action, but each action runs its own throwaway
# ``asyncio.run(...)`` in a background thread (see
# ``tui/views/notebook_detail.py``) — a fresh event loop every call, mirroring
# the "one client per event loop" rule already documented for
# ``NotebookLMClient`` (docs/python-api.md#concurrency-contract). A pooled
# asyncpg connection is bound to the loop it was opened on; reusing it from a
# later call's new loop raises
# ``RuntimeError: Task ... got Future ... attached to a different loop``.
# NullPool opens a fresh DBAPI connection per checkout and closes it on
# checkin, so no connection ever outlives the event loop that opened it — at
# the cost of a new connection per session, which is negligible next to the
# embedding/transcription HTTP calls each of these sessions already makes.
engine = create_async_engine(DATABASE_URL, echo=False, poolclass=NullPool)

async_session_maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing an async database session."""
    async with async_session_maker() as session:
        yield session
