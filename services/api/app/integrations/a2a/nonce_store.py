"""Atomic one-time nonce consumption backends.

The SQL backend intentionally expects a coordinator-owned migration for
``a2a_mandate_nonce_consumptions``. PostgreSQL's unique constraint is the
cross-process serialization point; an application-level read-before-write is
not sufficient for mandate replay protection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.models.a2a import A2AMandateNonceConsumption


class NonceClaimOutcome(StrEnum):
    CLAIMED = "CLAIMED"
    ALREADY_CLAIMED = "ALREADY_CLAIMED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class MandateNonceClaim:
    """Complete identity of one cryptographically verified mandate claim.

    ``claim_id`` is a digest of the canonical signed mandate data. Persisting it
    lets an activity retry recover an already committed verification without
    allowing the same nonce or mandate ID to authorize changed scope.
    """

    claim_id: str
    nonce: str
    mandate_id: str
    signer_key_id: str
    task_id: str
    merchant_id: str
    case_id: str
    customer_id: str
    recovery_action_id: str
    failed_invoice_id: str
    exact_amount_paise: int
    currency: str
    payment_surface_type: str
    payment_surface_reference: str
    authorized_action: str
    issued_at: datetime
    expires_at: datetime
    consumed_at: datetime


class NonceStore(Protocol):
    async def consume(
        self,
        claim: MandateNonceClaim,
        *,
        allow_new: bool = True,
    ) -> NonceClaimOutcome: ...


class InMemoryNonceStore:
    """Atomic mock store used in tests and explicit mock-provider mode."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._claims_by_nonce: dict[str, MandateNonceClaim] = {}
        self._nonce_by_mandate_id: dict[str, str] = {}

    async def consume(
        self,
        claim: MandateNonceClaim,
        *,
        allow_new: bool = True,
    ) -> NonceClaimOutcome:
        async with self._lock:
            existing = self._claims_by_nonce.get(claim.nonce)
            mandate_nonce = self._nonce_by_mandate_id.get(claim.mandate_id)
            if existing is None and mandate_nonce is None and allow_new:
                self._claims_by_nonce[claim.nonce] = claim
                self._nonce_by_mandate_id[claim.mandate_id] = claim.nonce
                return NonceClaimOutcome.CLAIMED
            if (
                existing is not None
                and existing.claim_id == claim.claim_id
                and mandate_nonce == claim.nonce
            ):
                return NonceClaimOutcome.ALREADY_CLAIMED
            return NonceClaimOutcome.CONFLICT


class SqlAlchemyNonceStore:
    """PostgreSQL single-statement nonce consumer for multi-process safety."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def consume(
        self,
        claim: MandateNonceClaim,
        *,
        allow_new: bool = True,
    ) -> NonceClaimOutcome:
        """Persist the full verified claim and recover identical activity retries."""

        statement = text(
            """
            INSERT INTO a2a_mandate_nonce_consumptions
                (nonce, mandate_id, claim_id, signer_key_id, task_id, merchant_id,
                 case_id, customer_id, recovery_action_id, failed_invoice_id,
                 exact_amount_paise, currency, payment_surface_type,
                 payment_surface_reference, authorized_action, issued_at,
                 expires_at, consumed_at, execution_status)
            VALUES
                (:nonce, :mandate_id, :claim_id, :signer_key_id, :task_id,
                 :merchant_id, :case_id, :customer_id, :recovery_action_id,
                 :failed_invoice_id, :exact_amount_paise, :currency,
                 :payment_surface_type, :payment_surface_reference,
                 :authorized_action, :issued_at, :expires_at, :consumed_at,
                 'AUTHORIZED')
            ON CONFLICT DO NOTHING
            RETURNING nonce
            """
        )
        parameters = {
            "nonce": claim.nonce,
            "mandate_id": claim.mandate_id,
            "claim_id": claim.claim_id,
            "signer_key_id": claim.signer_key_id,
            "task_id": claim.task_id,
            "merchant_id": claim.merchant_id,
            "case_id": claim.case_id,
            "customer_id": claim.customer_id,
            "recovery_action_id": claim.recovery_action_id,
            "failed_invoice_id": claim.failed_invoice_id,
            "exact_amount_paise": claim.exact_amount_paise,
            "currency": claim.currency,
            "payment_surface_type": claim.payment_surface_type,
            "payment_surface_reference": claim.payment_surface_reference,
            "authorized_action": claim.authorized_action,
            "issued_at": claim.issued_at,
            "expires_at": claim.expires_at,
            "consumed_at": claim.consumed_at,
        }
        async with self._session_factory() as session, session.begin():
            if allow_new:
                result = await session.execute(statement, parameters)
                if result.scalar_one_or_none() is not None:
                    return NonceClaimOutcome.CLAIMED

            # The INSERT may have committed in an earlier Temporal activity
            # attempt whose completion was lost. Only the byte-identical signed
            # claim is idempotent; every cross-claim collision remains replay.
            existing = (
                await session.scalars(
                    select(A2AMandateNonceConsumption).where(
                        or_(
                            A2AMandateNonceConsumption.nonce == claim.nonce,
                            A2AMandateNonceConsumption.mandate_id == claim.mandate_id,
                            A2AMandateNonceConsumption.claim_id == claim.claim_id,
                            A2AMandateNonceConsumption.recovery_action_id
                            == claim.recovery_action_id,
                        )
                    )
                )
            ).all()
            expected = (
                claim.claim_id,
                claim.nonce,
                claim.mandate_id,
                claim.signer_key_id,
                claim.task_id,
                claim.merchant_id,
                claim.case_id,
                claim.customer_id,
                claim.recovery_action_id,
                claim.failed_invoice_id,
                claim.exact_amount_paise,
                claim.currency,
                claim.payment_surface_type,
                claim.payment_surface_reference,
                claim.authorized_action,
                claim.issued_at,
                claim.expires_at,
            )
            for item in existing:
                persisted = (
                    item.claim_id,
                    item.nonce,
                    item.mandate_id,
                    item.signer_key_id,
                    item.task_id,
                    item.merchant_id,
                    item.case_id,
                    item.customer_id,
                    item.recovery_action_id,
                    item.failed_invoice_id,
                    item.exact_amount_paise,
                    item.currency,
                    item.payment_surface_type,
                    item.payment_surface_reference,
                    item.authorized_action,
                    item.issued_at,
                    item.expires_at,
                )
                if persisted == expected:
                    return NonceClaimOutcome.ALREADY_CLAIMED
            return NonceClaimOutcome.CONFLICT
