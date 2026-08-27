"""Lazy async database session construction.

Engine creation is lazy so importing the API router never opens a connection and
tests can override ``get_async_session`` without a configured database.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def _async_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return database_url


@lru_cache(maxsize=1)
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Build the process-wide session factory from the shared DATABASE_URL."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is required to use persistence endpoints")
    engine = create_async_engine(
        _async_database_url(database_url),
        pool_pre_ping=True,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_async_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one transactional unit of work."""

    async with get_session_factory()() as session:
        yield session
