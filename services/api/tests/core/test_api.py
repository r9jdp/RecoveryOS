"""Hosted-shape API contract smoke tests without editing the root application."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.api import install_core_api
from services.api.app.db import get_async_session
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.workflows import (
    WorkflowCommandDelivery,
    WorkflowCommandUnavailableError,
    get_recovery_workflow_commander,
)


class FakeWorkflowCommander:
    async def approval(self, **kwargs: object) -> WorkflowCommandDelivery:
        return WorkflowCommandDelivery(
            f"recovery-case:{kwargs['case_id']}",
            f"test:{kwargs['action_id']}",
            "DELIVERED",
        )

    async def stop(self, **kwargs: object) -> WorkflowCommandDelivery:
        return WorkflowCommandDelivery(
            f"recovery-case:{kwargs['case_id']}", "test:stop", "DELIVERED"
        )

    async def escalate(self, **kwargs: object) -> WorkflowCommandDelivery:
        return WorkflowCommandDelivery(
            f"recovery-case:{kwargs['case_id']}", "test:escalate", "DELIVERED"
        )


class FlakyWorkflowCommander(FakeWorkflowCommander):
    def __init__(self) -> None:
        self.attempts = 0

    async def approval(self, **kwargs: object) -> WorkflowCommandDelivery:
        self.attempts += 1
        if self.attempts == 1:
            raise WorkflowCommandUnavailableError(
                "Temporal unavailable",
                metadata={"reason": "TEMPORAL_RPC_FAILED"},
            )
        return await super().approval(**kwargs)


class RecordingWorkflowCommander(FakeWorkflowCommander):
    def __init__(self) -> None:
        self.commands: list[str] = []

    async def approval(self, **kwargs: object) -> WorkflowCommandDelivery:
        self.commands.append("APPROVE" if kwargs["approved"] else "REJECT")
        return await super().approval(**kwargs)

    async def stop(self, **kwargs: object) -> WorkflowCommandDelivery:
        self.commands.append("STOP")
        return await super().stop(**kwargs)

    async def escalate(self, **kwargs: object) -> WorkflowCommandDelivery:
        self.commands.append("ESCALATE_TO_HUMAN")
        return await super().escalate(**kwargs)


async def test_exported_router_serves_dashboard_case_and_timeline(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        await seed_fitbox(seed_session)

    app = FastAPI()
    install_core_api(app)

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as active_session:
            yield active_session

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_recovery_workflow_commander] = FakeWorkflowCommander
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        dashboard = await client.get("/v1/dashboard/metrics")
        case_list = await client.get("/v1/recovery-cases")
        detail = await client.get(f"/v1/recovery-cases/{FITBOX_CASE_ID}")
        timeline = await client.get(f"/v1/recovery-cases/{FITBOX_CASE_ID}/timeline")
        recommendation = await client.post(
            f"/v1/recovery-cases/{FITBOX_CASE_ID}/actions/recommend", json={}
        )
        approval = await client.post(
            f"/v1/recovery-cases/{FITBOX_CASE_ID}/commands",
            json={"command": "APPROVE"},
        )
        success_payload = {
            "provider_event_id": "evt_api_contract_success",
            "amount_paise": 149_900,
            "subscription_reactivated": True,
        }
        success = await client.post(
            f"/v1/mock/recovery-cases/{FITBOX_CASE_ID}/payment-success",
            json=success_payload,
        )
        duplicate_success = await client.post(
            f"/v1/mock/recovery-cases/{FITBOX_CASE_ID}/payment-success",
            json=success_payload,
        )
        missing = await client.get("/v1/recovery-cases/missing")

    assert dashboard.status_code == 200
    assert dashboard.json()["metrics"]["revenue_at_risk_paise"] == 149_900
    assert case_list.status_code == 200
    assert case_list.json()["page"] == {
        "next_cursor": None,
        "has_more": False,
        "limit": 25,
    }
    assert detail.status_code == 200
    assert detail.json()["case"]["id"] == FITBOX_CASE_ID
    assert timeline.status_code == 200
    assert len(timeline.json()["items"]) == 3
    assert recommendation.status_code == 201
    assert recommendation.json()["action"]["payment_surface_type"] == ("SUBSCRIPTION_CARD_UPDATE")
    assert approval.status_code == 200
    assert approval.json()["status"] == "ACCEPTED"
    assert success.status_code == 200
    assert success.json()["newly_recognized"] is True
    assert success.json()["case"]["case_outcome"] == "RECOVERED"
    assert duplicate_success.status_code == 200
    assert duplicate_success.json()["newly_recognized"] is False
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"


async def test_approval_is_durable_and_retryable_when_signal_delivery_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        await seed_fitbox(seed_session)

    app = FastAPI()
    install_core_api(app)
    commander = FlakyWorkflowCommander()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as active_session:
            yield active_session

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_recovery_workflow_commander] = lambda: commander
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        first = await client.post(
            f"/v1/recovery-cases/{FITBOX_CASE_ID}/commands",
            json={"command": "APPROVE"},
        )
        detail = await client.get(f"/v1/recovery-cases/{FITBOX_CASE_ID}")
        retried = await client.post(
            f"/v1/recovery-cases/{FITBOX_CASE_ID}/commands",
            json={"command": "APPROVE"},
        )

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "RECOVERY_WORKFLOW_UNAVAILABLE"
    assert detail.json()["latest_action"]["status"] == "SCHEDULED"
    assert detail.json()["latest_action"]["customer_url"] is None
    assert retried.status_code == 200
    assert commander.attempts == 2


@pytest.mark.parametrize("command", ["APPROVE", "REJECT", "STOP", "ESCALATE_TO_HUMAN"])
async def test_operator_command_facade_delivers_every_temporal_signal_path(
    command: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as seed_session:
        await seed_fitbox(seed_session)

    app = FastAPI()
    install_core_api(app)
    commander = RecordingWorkflowCommander()

    async def override_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as active_session:
            yield active_session

    app.dependency_overrides[get_async_session] = override_session
    app.dependency_overrides[get_recovery_workflow_commander] = lambda: commander
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/recovery-cases/{FITBOX_CASE_ID}/commands",
            json={"command": command},
        )

    assert response.status_code == 200
    assert commander.commands == [command]
