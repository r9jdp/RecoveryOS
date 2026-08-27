from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.integrations.razorpay.normalizer import normalize_webhook
from services.api.app.integrations.razorpay.signature import webhook_signature
from services.api.app.models import Merchant, OutboxMessage, WebhookInboxEntry
from services.api.app.webhooks.razorpay import RazorpayWebhookIngestionService
from services.api.app.webhooks.repository import InboxOutboxStore

FIXTURES = Path("services/api/tests/fixtures/razorpay")
SECRET = "test_webhook_secret"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine, expire_on_commit=False) as active_session:
        active_session.add(
            Merchant(
                id="merchant_fitbox",
                external_id="acc_fitbox_test",
                display_name="FitBox",
            )
        )
        await active_session.commit()
        yield active_session
    await engine.dispose()


async def test_signature_first_ingestion_atomically_enqueues_and_deduplicates(
    session: AsyncSession,
) -> None:
    raw_body = (FIXTURES / "payment.failed.json").read_bytes()
    service = RazorpayWebhookIngestionService(InboxOutboxStore(session))
    signature = webhook_signature(raw_body, SECRET)

    first = await service.ingest(
        merchant_id="merchant_fitbox",
        raw_body=raw_body,
        signature=signature,
        provider_event_id="evt_payment_failed_001",
        webhook_secret=SECRET,
    )
    duplicate = await service.ingest(
        merchant_id="merchant_fitbox",
        raw_body=raw_body,
        signature=signature,
        provider_event_id="evt_payment_failed_001",
        webhook_secret=SECRET,
    )

    assert first.accepted is True
    assert first.duplicate is False
    assert first.acknowledge_within_sla is True
    assert first.acknowledge_elapsed_ms < 5_000
    assert duplicate.duplicate is True
    assert duplicate.inbox_id == first.inbox_id
    assert duplicate.outbox_id == first.outbox_id
    assert await session.scalar(select(func.count()).select_from(WebhookInboxEntry)) == 1
    assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1


async def test_outbox_conflict_rolls_back_new_inbox(session: AsyncSession) -> None:
    raw_payload = __import__("json").loads(
        (FIXTURES / "payment.captured.json").read_text(encoding="utf-8")
    )
    event = normalize_webhook(provider_event_id="evt_atomic", payload=raw_payload)
    digest = InboxOutboxStore._event_digest(  # noqa: SLF001 - collision fixture
        merchant_id="merchant_fitbox", provider_event_id="evt_atomic"
    )
    session.add(
        OutboxMessage(
            aggregate_type="preexisting",
            aggregate_id="other",
            event_type="OTHER",
            payload={},
            deduplication_key=f"razorpay:{digest}",
        )
    )
    await session.commit()

    with pytest.raises(IntegrityError):
        await InboxOutboxStore(session).persist(merchant_id="merchant_fitbox", event=event)

    assert await session.scalar(select(func.count()).select_from(WebhookInboxEntry)) == 0
    assert await session.scalar(select(func.count()).select_from(OutboxMessage)) == 1
