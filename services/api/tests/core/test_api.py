"""Hosted-shape API contract smoke tests without editing the root application."""

from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.api import install_core_api
from services.api.app.db import get_async_session
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox


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
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RESOURCE_NOT_FOUND"
