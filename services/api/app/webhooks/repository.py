"""Atomic webhook inbox/outbox persistence."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.integrations.razorpay.models import (
    NormalizedRazorpayEvent,
    RazorpayOutboxPayload,
)
from services.api.app.models import OutboxMessage, WebhookInboxEntry


@dataclass(frozen=True, slots=True)
class InboxOutboxWrite:
    inbox_id: str
    outbox_id: str
    duplicate: bool


class InboxOutboxStore:
    """Persist receipt and dispatch intent in one database transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _find_existing(
        self, *, merchant_id: str, provider_event_id: str
    ) -> WebhookInboxEntry | None:
        return cast(
            WebhookInboxEntry | None,
            await self.session.scalar(
                select(WebhookInboxEntry).where(
                    WebhookInboxEntry.merchant_id == merchant_id,
                    WebhookInboxEntry.provider == "razorpay",
                    WebhookInboxEntry.provider_event_id == provider_event_id,
                )
            ),
        )

    @staticmethod
    def _event_digest(*, merchant_id: str, provider_event_id: str) -> str:
        return hashlib.sha256(f"{merchant_id}:{provider_event_id}".encode()).hexdigest()

    async def _find_outbox(
        self, *, merchant_id: str, provider_event_id: str
    ) -> OutboxMessage | None:
        digest = self._event_digest(merchant_id=merchant_id, provider_event_id=provider_event_id)
        return cast(
            OutboxMessage | None,
            await self.session.scalar(
                select(OutboxMessage).where(OutboxMessage.deduplication_key == f"razorpay:{digest}")
            ),
        )

    async def persist(
        self,
        *,
        merchant_id: str,
        event: NormalizedRazorpayEvent,
    ) -> InboxOutboxWrite:
        existing = await self._find_existing(
            merchant_id=merchant_id, provider_event_id=event.provider_event_id
        )
        if existing is not None:
            outbox = await self._find_outbox(
                merchant_id=merchant_id, provider_event_id=event.provider_event_id
            )
            if outbox is None:
                raise RuntimeError("webhook inbox exists without its atomic outbox message")
            return InboxOutboxWrite(existing.id, outbox.id, duplicate=True)

        inbox = WebhookInboxEntry(
            merchant_id=merchant_id,
            provider="razorpay",
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            payload=event.provider_payload,
            occurred_at=event.occurred_at,
        )
        digest = self._event_digest(
            merchant_id=merchant_id, provider_event_id=event.provider_event_id
        )
        outbox = OutboxMessage(
            aggregate_type="razorpay_webhook",
            aggregate_id=digest,
            event_type="RAZORPAY_WEBHOOK_RECEIVED",
            payload=RazorpayOutboxPayload(
                merchant_id=merchant_id,
                event=event,
            ).model_dump(mode="json"),
            deduplication_key=f"razorpay:{digest}",
        )
        self.session.add_all([inbox, outbox])
        try:
            await self.session.commit()
        except IntegrityError:
            # A competing request may have won the provider-event uniqueness race.
            # Roll back both inserts before reading the winning atomic pair.
            await self.session.rollback()
            existing = await self._find_existing(
                merchant_id=merchant_id, provider_event_id=event.provider_event_id
            )
            outbox = await self._find_outbox(
                merchant_id=merchant_id, provider_event_id=event.provider_event_id
            )
            if existing is None or outbox is None:
                raise
            return InboxOutboxWrite(existing.id, outbox.id, duplicate=True)
        return InboxOutboxWrite(inbox.id, outbox.id, duplicate=False)
