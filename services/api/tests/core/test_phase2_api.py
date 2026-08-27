"""Coordinator-owned Phase 2 HTTP integration tests."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.api import install_core_api
from services.api.app.api.router import get_razorpay_webhook_secret
from services.api.app.db import get_async_session
from services.api.app.models import Customer, OutboxMessage, WebhookInboxEntry
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox

FIXTURES = Path(__file__).parents[1] / "fixtures" / "razorpay"


async def test_policy_settings_put_is_allowed_by_browser_cors() -> None:
    from services.api.app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.options(
            "/v1/policy-settings",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "PUT",
            },
        )

    assert response.status_code == 200
    assert "PUT" in response.headers["access-control-allow-methods"]


async def test_phase2_policy_webhook_and_opt_out_http_contracts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        await seed_fitbox(seed_session)

    app = FastAPI()
    install_core_api(app)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as active_session:
            yield active_session

    secret = "phase2-webhook-test-secret"
    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_razorpay_webhook_secret] = lambda: secret
    raw_body = (FIXTURES / "payment.failed.json").read_bytes()
    signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    webhook_headers = {
        "X-Razorpay-Signature": signature,
        "X-Razorpay-Event-Id": "evt_phase2_http_contract",
    }

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        settings = await client.get("/v1/policy-settings")
        updated_settings = await client.put(
            "/v1/policy-settings",
            json={
                "timezone": "Asia/Kolkata",
                "quiet_hours_start": "21:00",
                "quiet_hours_end": "08:00",
                "max_contacts_per_7_days": 1,
                "require_approval_above_paise": 149_900,
                "require_approval_actions": ["START_VOICE"],
                "recovery_kill_switch": True,
            },
        )
        first_webhook = await client.post(
            "/v1/webhooks/razorpay", content=raw_body, headers=webhook_headers
        )
        duplicate_webhook = await client.post(
            "/v1/webhooks/razorpay", content=raw_body, headers=webhook_headers
        )
        invalid_signature = await client.post(
            "/v1/webhooks/razorpay",
            content=raw_body,
            headers={**webhook_headers, "X-Razorpay-Signature": "invalid"},
        )
        opt_out = await client.post(
            f"/v1/recovery-cases/{FITBOX_CASE_ID}/safety-dispositions",
            json={"disposition": "MARK_OPT_OUT"},
        )

    assert settings.status_code == 200
    assert settings.json()["version"] == 1
    assert updated_settings.status_code == 200
    assert updated_settings.json()["recovery_kill_switch"] is True
    assert updated_settings.json()["require_approval_actions"] == ["START_VOICE"]
    assert updated_settings.json()["version"] == 2
    assert first_webhook.status_code == 202
    assert first_webhook.json()["duplicate"] is False
    assert first_webhook.json()["acknowledge_within_sla"] is True
    assert duplicate_webhook.status_code == 202
    assert duplicate_webhook.json()["duplicate"] is True
    assert invalid_signature.status_code == 401
    assert invalid_signature.json()["error"]["code"] == ("RAZORPAY_WEBHOOK_SIGNATURE_INVALID")
    assert opt_out.status_code == 200
    assert opt_out.json()["case"]["contact_disposition"] == "OPTED_OUT"
    assert opt_out.json()["case"]["case_outcome"] == "STOPPED"

    async with session_factory() as verification_session:
        inbox_count = await verification_session.scalar(select(func.count(WebhookInboxEntry.id)))
        outbox_count = await verification_session.scalar(select(func.count(OutboxMessage.id)))
        customer = await verification_session.get(Customer, "customer_fitbox_001")
    assert inbox_count == 1
    assert outbox_count == 1
    assert customer is not None
    assert customer.opted_out_at is not None
