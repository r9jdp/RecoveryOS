"""Atomic one-time nonce consumption backends.

The SQL backend intentionally expects a coordinator-owned migration for
``a2a_mandate_nonce_consumptions``. PostgreSQL's unique constraint is the
cross-process serialization point; an application-level read-before-write is
not sufficient for mandate replay protection.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class NonceStore(Protocol):
    async def consume(
        self,
        *,
        nonce: str,
        mandate_id: str,
        signer_key_id: str,
        merchant_id: str,
        case_id: str,
        expires_at: datetime,
        consumed_at: datetime,
    ) -> bool: ...


class InMemoryNonceStore:
    """Atomic mock store used in tests and explicit mock-provider mode."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._consumed: set[str] = set()

    async def consume(
        self,
        *,
        nonce: str,
        mandate_id: str,
        signer_key_id: str,
        merchant_id: str,
        case_id: str,
        expires_at: datetime,
        consumed_at: datetime,
    ) -> bool:
        del mandate_id, signer_key_id, merchant_id, case_id, expires_at, consumed_at
        async with self._lock:
            if nonce in self._consumed:
                return False
            self._consumed.add(nonce)
            return True


class SqlAlchemyNonceStore:
    """PostgreSQL single-statement nonce consumer for multi-process safety."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def consume(
        self,
        *,
        nonce: str,
        mandate_id: str,
        signer_key_id: str,
        merchant_id: str,
        case_id: str,
        expires_at: datetime,
        consumed_at: datetime,
    ) -> bool:
        statement = text(
            """
            INSERT INTO a2a_mandate_nonce_consumptions
                (nonce, mandate_id, signer_key_id, merchant_id, case_id, expires_at, consumed_at)
            VALUES
                (:nonce, :mandate_id, :signer_key_id, :merchant_id, :case_id,
                 :expires_at, :consumed_at)
            ON CONFLICT (nonce) DO NOTHING
            RETURNING nonce
            """
        )
        async with self._session_factory() as session, session.begin():
            result = await session.execute(
                statement,
                {
                    "nonce": nonce,
                    "mandate_id": mandate_id,
                    "signer_key_id": signer_key_id,
                    "merchant_id": merchant_id,
                    "case_id": case_id,
                    "expires_at": expires_at,
                    "consumed_at": consumed_at,
                },
            )
            return result.scalar_one_or_none() is not None
