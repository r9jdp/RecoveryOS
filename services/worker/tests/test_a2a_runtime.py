from __future__ import annotations

import base64
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from services.api.app.integrations.a2a.mandates import MandateVerifier, canonical_json
from services.api.app.integrations.a2a.models import RecoveryMandateData
from services.api.app.integrations.a2a.nonce_store import (
    InMemoryNonceStore,
    SqlAlchemyNonceStore,
)
from services.api.app.providers.contracts import (
    CustomerAgentRecoveryRequest,
    CustomerAgentTask,
)
from services.worker.app.a2a_runtime import LiveA2AMandateActivityServices
from services.worker.app.contracts import (
    PollA2AMandateInput,
    StartA2AAuthorizationInput,
)

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


@dataclass
class FakeCustomerAgentClient:
    task: CustomerAgentTask
    requests: list[CustomerAgentRecoveryRequest] = field(default_factory=list)

    async def send_recovery_request(
        self, request: CustomerAgentRecoveryRequest
    ) -> CustomerAgentTask:
        self.requests.append(request)
        return self.task

    async def get_task(self, *, remote_task_id: str) -> CustomerAgentTask:
        assert remote_task_id == self.task.remote_task_id
        return self.task

    async def cancel_task(self, *, remote_task_id: str, reason: str) -> CustomerAgentTask:
        del reason
        assert remote_task_id == self.task.remote_task_id
        return self.task


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def signed_artifact(
    *,
    issued_at: datetime = NOW,
    expires_at: datetime = NOW + timedelta(minutes=10),
) -> tuple[dict[str, Any], str]:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    data = RecoveryMandateData(
        protocol_version="recovery.mandate.v1",
        mandate_id="mandate-1",
        nonce="nonce-1",
        signer_key_id="customer-key-1",
        task_id="task-1",
        merchant_id="merchant-1",
        case_id="case-1",
        customer_id="customer-1",
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference="invoice-1",
        authorized_action="OPEN_EXACT_PAYMENT_SURFACE",
        issued_at=issued_at,
        expires_at=expires_at,
    )
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return (
        {
            "algorithm": "Ed25519",
            "data": data.model_dump(mode="json"),
            "signature": _b64url(private_key.sign(canonical_json(data))),
        },
        _b64url(public_key),
    )


def poll_command() -> PollA2AMandateInput:
    return PollA2AMandateInput(
        remote_task_id="task-1",
        case_id="case-1",
        merchant_id="merchant-1",
        customer_id="customer-1",
        exact_amount_paise=149_900,
        currency="INR",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        payment_surface_reference="invoice-1",
        recovery_deadline=(NOW + timedelta(minutes=15)).isoformat(),
    )


def live_services(
    *,
    artifact: dict[str, Any],
    public_key: str,
    nonce_store: InMemoryNonceStore | SqlAlchemyNonceStore,
) -> LiveA2AMandateActivityServices:
    task = CustomerAgentTask(
        remote_task_id="task-1",
        state="WORKING",
        artifact=artifact,
        updated_at=NOW,
    )
    return LiveA2AMandateActivityServices(
        client=FakeCustomerAgentClient(task),
        verifier=MandateVerifier(
            pinned_public_keys={"customer-key-1": public_key},
            nonce_store=nonce_store,
        ),
        clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_live_bridge_starts_exact_request_and_sql_nonce_is_consumed_once() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.execute(
            text(
                """
                CREATE TABLE a2a_mandate_nonce_consumptions (
                    nonce TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL UNIQUE,
                    signer_key_id TEXT NOT NULL,
                    merchant_id TEXT NOT NULL,
                    case_id TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL,
                    consumed_at TIMESTAMP NOT NULL
                )
                """
            )
        )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    artifact, public_key = signed_artifact()
    services = live_services(
        artifact=artifact,
        public_key=public_key,
        nonce_store=SqlAlchemyNonceStore(session_factory),
    )

    started = await services.start_authorization(
        StartA2AAuthorizationInput(
            case_id="case-1",
            merchant_id="merchant-1",
            customer_id="customer-1",
            exact_amount_paise=149_900,
            currency="INR",
            payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
            payment_surface_reference="invoice-1",
            recovery_deadline=(NOW + timedelta(minutes=15)).isoformat(),
            idempotency_key="case-1:SEND_TO_CUSTOMER_AGENT:1",
        )
    )
    assert started.remote_task_id == "task-1"
    client = services.client
    assert isinstance(client, FakeCustomerAgentClient)
    assert client.requests[0].payment_surface_reference == "invoice-1"

    verified = await services.poll_and_verify_mandate(poll_command())
    replayed = await services.poll_and_verify_mandate(poll_command())
    assert verified.verification_status == "VERIFIED"
    assert verified.mandate_id == "mandate-1"
    assert verified.verified_artifact == artifact
    assert replayed.verification_status == "REJECTED"
    assert replayed.reason_code == "REPLAYED"
    await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        replace(poll_command(), merchant_id="merchant-wrong"),
        replace(poll_command(), case_id="case-wrong"),
        replace(poll_command(), exact_amount_paise=149_901),
        replace(poll_command(), payment_surface_reference="invoice-wrong"),
        replace(poll_command(), payment_surface_type="SUBSCRIPTION_CARD_UPDATE"),
    ],
)
async def test_live_bridge_rejects_every_scope_confusion(
    command: PollA2AMandateInput,
) -> None:
    artifact, public_key = signed_artifact()
    services = live_services(
        artifact=artifact,
        public_key=public_key,
        nonce_store=InMemoryNonceStore(),
    )
    rejected = await services.poll_and_verify_mandate(command)
    assert rejected.verification_status == "REJECTED"
    assert rejected.reason_code == "SCOPE_MISMATCH"


@pytest.mark.asyncio
async def test_live_bridge_rejects_expired_and_over_deadline_mandates() -> None:
    expired, public_key = signed_artifact(
        issued_at=NOW - timedelta(minutes=20),
        expires_at=NOW - timedelta(minutes=10),
    )
    expired_services = live_services(
        artifact=expired,
        public_key=public_key,
        nonce_store=InMemoryNonceStore(),
    )
    expired_result = await expired_services.poll_and_verify_mandate(poll_command())
    assert expired_result.reason_code == "EXPIRED"

    over_deadline, public_key = signed_artifact(expires_at=NOW + timedelta(minutes=20))
    deadline_services = live_services(
        artifact=over_deadline,
        public_key=public_key,
        nonce_store=InMemoryNonceStore(),
    )
    deadline_result = await deadline_services.poll_and_verify_mandate(poll_command())
    assert deadline_result.reason_code == "EXPIRES_AFTER_RECOVERY_DEADLINE"
