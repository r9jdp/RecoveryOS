"""Signature-first, acknowledge-first Razorpay webhook ingestion."""

from __future__ import annotations

from time import perf_counter
from typing import Any, cast

import orjson
from pydantic import BaseModel, ConfigDict, Field

from services.api.app.integrations.razorpay.errors import RazorpayContractError
from services.api.app.integrations.razorpay.normalizer import normalize_webhook
from services.api.app.integrations.razorpay.signature import verify_webhook_signature

from .repository import InboxOutboxStore


class WebhookIngestionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_event_id: str
    inbox_id: str
    outbox_id: str
    accepted: bool
    duplicate: bool
    acknowledge_elapsed_ms: float = Field(ge=0)
    acknowledge_within_sla: bool


class RazorpayWebhookIngestionService:
    """Authenticate and durably enqueue only; provider work happens after the ACK."""

    def __init__(
        self,
        store: InboxOutboxStore,
        *,
        acknowledge_deadline_seconds: float = 5.0,
    ) -> None:
        if acknowledge_deadline_seconds <= 0 or acknowledge_deadline_seconds > 5:
            raise ValueError("acknowledge deadline must be in (0, 5] seconds")
        self.store = store
        self.acknowledge_deadline_seconds = acknowledge_deadline_seconds

    async def ingest(
        self,
        *,
        merchant_id: str,
        raw_body: bytes,
        signature: str,
        provider_event_id: str,
        webhook_secret: str,
    ) -> WebhookIngestionReceipt:
        started_at = perf_counter()
        verify_webhook_signature(raw_body, signature, webhook_secret)
        try:
            decoded = orjson.loads(raw_body)
        except orjson.JSONDecodeError as error:
            raise RazorpayContractError(
                "RAZORPAY_WEBHOOK_JSON_INVALID", "Webhook body is not valid JSON."
            ) from error
        if not isinstance(decoded, dict):
            raise RazorpayContractError(
                "RAZORPAY_WEBHOOK_JSON_INVALID", "Webhook body must be a JSON object."
            )
        event = normalize_webhook(
            provider_event_id=provider_event_id.strip(),
            payload=cast(dict[str, Any], decoded),
        )
        write = await self.store.persist(merchant_id=merchant_id, event=event)
        elapsed_seconds = perf_counter() - started_at
        return WebhookIngestionReceipt(
            provider_event_id=event.provider_event_id,
            inbox_id=write.inbox_id,
            outbox_id=write.outbox_id,
            accepted=True,
            duplicate=write.duplicate,
            acknowledge_elapsed_ms=elapsed_seconds * 1_000,
            acknowledge_within_sla=elapsed_seconds <= self.acknowledge_deadline_seconds,
        )
