from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from app.config import CustomerAgentSettings
from app.main import create_app

from services.api.app.domain.enums import PaymentSurfaceType
from services.api.app.integrations.a2a.client import A2ACustomerAgentClient
from services.api.app.providers.contracts import CustomerAgentRecoveryRequest


@pytest.mark.asyncio
async def test_frozen_customer_agent_client_maps_auth_required_and_cancel() -> None:
    app = create_app(CustomerAgentSettings(origin="https://customer.example"))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://customer.example",
    ) as http_client:
        client = A2ACustomerAgentClient(
            origin="https://customer.example",
            client=http_client,
        )
        task = await client.send_recovery_request(
            CustomerAgentRecoveryRequest(
                idempotency_key="merchant-1:case-1:a2a",
                case_id="case-1",
                merchant_id="merchant-1",
                customer_id="customer-1",
                exact_amount_paise=149900,
                currency="INR",
                payment_surface_type=PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
                payment_surface_reference="inv_123",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
                context={"merchant_display_name": "FitBox"},
            )
        )
        assert task.state == "AUTH_REQUIRED"
        fetched = await client.get_task(remote_task_id=task.remote_task_id)
        assert fetched == task
        canceled = await client.cancel_task(
            remote_task_id=task.remote_task_id,
            reason="Payment captured elsewhere",
        )
        assert canceled.state == "CANCELED"
