from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from services.api.app.db import Base
from services.api.app.domain.enums import ActionStatus, PolicyDisposition
from services.api.app.integrations.razorpay.client import RazorpayClient, RazorpayConfig
from services.api.app.models import (  # noqa: F401 - register model metadata
    Merchant,
    PolicyDecisionRecord,
)
from services.api.app.reliability.registry import CircuitBreakerRegistry
from services.worker.app.runtime import ProductionRecoveryActivityServices
from services.worker.tests.test_payment_surface_runtime import (
    FixedScorer,
    _command,
    _seed_standard_action,
)


@pytest.fixture
async def ambiguous_runtime_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def ambiguous_runtime_sessions(
    ambiguous_runtime_engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(ambiguous_runtime_engine, expire_on_commit=False)


@pytest.mark.parametrize(
    ("lookup_outcome", "expected_status", "expected_reason", "expected_creates"),
    [
        ("found", "SUCCEEDED", "SUBMISSION_RECONCILED", 1),
        ("absent", "SUCCEEDED", "CONFIRMED_ABSENT_RESUBMITTED", 2),
        ("unresolved", "UNCERTAIN", "PAYMENT_LINK_RECONCILIATION_UNRESOLVED", 1),
    ],
)
async def test_ambiguous_5xx_create_converges_only_through_reference_lookup(
    lookup_outcome: str,
    expected_status: str,
    expected_reason: str,
    expected_creates: int,
    ambiguous_runtime_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    action = await _seed_standard_action(ambiguous_runtime_sessions, status=ActionStatus.PROPOSED)
    async with ambiguous_runtime_sessions() as session:
        policy = await session.scalar(
            select(PolicyDecisionRecord).where(PolicyDecisionRecord.action_id == action.id)
        )
        assert policy is not None
        policy.disposition = PolicyDisposition.ALLOW
        policy.decision_code = "TEST_AMBIGUOUS_LINK_ALLOWED"
        await session.commit()
    monkeypatch.setattr(
        "services.worker.app.runtime.get_session_factory",
        lambda: ambiguous_runtime_sessions,
    )
    reference_id = "rec_" + hashlib.sha256(_command().idempotency_key.encode()).hexdigest()[:32]
    create_attempts = 0
    lookup_attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal create_attempts, lookup_attempts
        if request.url.path == "/v1/subscriptions/sub_fitbox_annual_001":
            return httpx.Response(200, json={"status": "halted"})
        if request.method == "GET" and request.url.path == "/v1/payment_links":
            lookup_attempts += 1
            assert request.url.params["reference_id"] == reference_id
            if lookup_outcome == "unresolved":
                return httpx.Response(503, json={"error": {"code": "SERVER_ERROR"}})
            if lookup_outcome == "absent":
                return httpx.Response(200, json={"payment_links": []})
            return httpx.Response(
                200,
                json={
                    "payment_links": [
                        {
                            "id": "plink_reconciled",
                            "reference_id": reference_id,
                            "short_url": "https://rzp.test/i/reconciled",
                        }
                    ]
                },
            )
        create_attempts += 1
        if create_attempts == 1:
            return httpx.Response(503, json={"error": {"code": "SERVER_ERROR"}})
        return httpx.Response(
            200,
            json={"id": "plink_after_absence", "short_url": "https://rzp.test/i/after"},
        )

    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.razorpay.test",
    )
    provider = RazorpayClient(
        RazorpayConfig(
            key_id=f"rzp_test_{lookup_outcome}",
            key_secret="test_secret",
            checkout_origin="https://recovery.test",
            base_url="https://api.razorpay.test",
        ),
        client=http_client,
        breaker_registry=CircuitBreakerRegistry(),
    )
    services = ProductionRecoveryActivityServices(
        payment_provider=provider,
        scorer=FixedScorer(),
    )

    result = await services.execute_recovery_action(_command())

    assert result.status == expected_status
    assert result.reason_code == expected_reason
    assert create_attempts == expected_creates
    assert lookup_attempts == 1
    await http_client.aclose()
