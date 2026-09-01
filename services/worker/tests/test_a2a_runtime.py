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

from services.api.app.db import Base
from services.api.app.integrations.a2a.mandates import MandateVerifier, canonical_json
from services.api.app.integrations.a2a.models import RecoveryMandateData
from services.api.app.integrations.a2a.nonce_store import (
    InMemoryNonceStore,
    SqlAlchemyNonceStore,
)
from services.api.app.providers.contracts import (
    CustomerAgentDisplayContext,
    CustomerAgentRecoveryRequest,
    CustomerAgentTask,
)
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.worker.app.a2a_runtime import (
    LiveA2AMandateActivityServices,
    SqlAlchemyA2ADisplayContextLoader,
)
from services.worker.app.contracts import (
    PollA2AMandateInput,
    SendA2APaymentReceiptInput,
    StartA2AAuthorizationInput,
)

NOW = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)


@dataclass
class FakeCustomerAgentClient:
    task: CustomerAgentTask
    requests: list[CustomerAgentRecoveryRequest] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)

    async def send_recovery_request(
        self, request: CustomerAgentRecoveryRequest
    ) -> CustomerAgentTask:
        self.requests.append(request)
        return self.task

    async def get_task(self, *, remote_task_id: str) -> CustomerAgentTask:
        assert remote_task_id == self.task.remote_task_id
        return self.task

    async def send_payment_receipt(self, **receipt: Any) -> CustomerAgentTask:
        assert receipt["remote_task_id"] == self.task.remote_task_id
        self.receipts.append(receipt)
        return self.task.model_copy(update={"state": "COMPLETED"})

    async def cancel_task(self, *, remote_task_id: str, reason: str) -> CustomerAgentTask:
        del reason
        assert remote_task_id == self.task.remote_task_id
        return self.task


@dataclass
class FakeDisplayContextLoader:
    contexts: list[tuple[str, str, str]] = field(default_factory=list)

    async def load(
        self,
        *,
        case_id: str,
        merchant_id: str,
        customer_id: str,
    ) -> CustomerAgentDisplayContext:
        self.contexts.append((case_id, merchant_id, customer_id))
        return CustomerAgentDisplayContext(
            merchant_display_name="FitBox",
            plan_name="FitBox Annual",
            failure_explanation=(
                "The payment needs customer authentication before it can continue."
            ),
        )


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
        display_context_loader=FakeDisplayContextLoader(),
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
    assert client.requests[0].context == CustomerAgentDisplayContext(
        merchant_display_name="FitBox",
        plan_name="FitBox Annual",
        failure_explanation=("The payment needs customer authentication before it can continue."),
    )
    loader = services.display_context_loader
    assert isinstance(loader, FakeDisplayContextLoader)
    assert loader.contexts == [("case-1", "merchant-1", "customer-1")]

    verified = await services.poll_and_verify_mandate(poll_command())
    replayed = await services.poll_and_verify_mandate(poll_command())
    assert verified.verification_status == "VERIFIED"
    assert verified.mandate_id == "mandate-1"
    assert verified.verified_artifact is None
    assert replayed.verification_status == "REJECTED"
    assert replayed.reason_code == "REPLAYED"

    receipt = await services.send_payment_receipt(
        SendA2APaymentReceiptInput(
            remote_task_id="task-1",
            mandate_id="mandate-1",
            merchant_id="merchant-1",
            case_id="case-1",
            exact_amount_paise=149_900,
            currency="INR",
            provider_reference="pay-captured-1",
            observed_at=NOW.isoformat(),
            idempotency_key="task-1:mandate-1:recovery.receipt.v1",
        )
    )
    assert receipt.delivered is True
    assert receipt.task_state == "COMPLETED"
    assert client.receipts == [
        {
            "remote_task_id": "task-1",
            "mandate_id": "mandate-1",
            "merchant_id": "merchant-1",
            "case_id": "case-1",
            "exact_amount_paise": 149_900,
            "currency": "INR",
            "provider_reference": "pay-captured-1",
            "observed_at": NOW,
            "idempotency_key": "task-1:mandate-1:recovery.receipt.v1",
        }
    ]
    await engine.dispose()


@pytest.mark.asyncio
async def test_display_context_is_loaded_from_exact_database_case_without_raw_failure_data() -> (
    None
):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        await seed_fitbox(session)

    loader = SqlAlchemyA2ADisplayContextLoader(session_factory)
    context = await loader.load(
        case_id=FITBOX_CASE_ID,
        merchant_id="merchant_fitbox",
        customer_id="customer_fitbox_001",
    )
    assert context == CustomerAgentDisplayContext(
        merchant_display_name="FitBox",
        plan_name="FitBox Annual",
        failure_explanation=("The payment needs customer authentication before it can continue."),
    )
    serialized = context.model_dump_json()
    assert "incorrect_otp" not in serialized.casefold()
    assert "pay_" not in serialized.casefold()

    with pytest.raises(ValueError, match="does not match"):
        await loader.load(
            case_id=FITBOX_CASE_ID,
            merchant_id="merchant_wrong",
            customer_id="customer_fitbox_001",
        )
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
