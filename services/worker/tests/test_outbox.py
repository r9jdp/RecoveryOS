from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from temporalio.client import Client

from services.api.app.db import Base
from services.api.app.integrations.razorpay.normalizer import normalize_webhook
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.webhooks import RazorpayDownstreamSignal
from services.worker.app.contracts import PaymentEventSignal, RecoveryWorkflowInput
from services.worker.app.outbox import TemporalRazorpaySignalDispatcher

FIXTURES = Path("services/api/tests/fixtures/razorpay")


class FakeWorkflowHandle:
    def __init__(self) -> None:
        self.signals: list[tuple[str, object]] = []

    async def signal(self, signal_name: str, arg: object) -> None:
        self.signals.append((signal_name, arg))


class FakeTemporalClient:
    def __init__(self) -> None:
        self.handle = FakeWorkflowHandle()
        self.starts: list[tuple[object, RecoveryWorkflowInput, dict[str, Any]]] = []

    async def start_workflow(
        self,
        workflow: object,
        command: RecoveryWorkflowInput,
        **options: Any,
    ) -> FakeWorkflowHandle:
        self.starts.append((workflow, command, options))
        return self.handle

    def get_workflow_handle(self, workflow_id: str) -> FakeWorkflowHandle:
        del workflow_id
        return self.handle


async def test_captured_outbox_starts_invoice_workflow_and_signals_payment() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            await seed_fitbox(session)
            raw = json.loads((FIXTURES / "payment.captured.json").read_text(encoding="utf-8"))
            event = normalize_webhook(provider_event_id="evt_worker_capture", payload=raw)
            fake_client = FakeTemporalClient()
            dispatcher = TemporalRazorpaySignalDispatcher(
                session,
                cast(Client, fake_client),
                task_queue="recovery-os-test",
            )

            await dispatcher(
                RazorpayDownstreamSignal(
                    idempotency_key="razorpay:worker-capture",
                    merchant_id="merchant_fitbox",
                    provider_event_id=event.provider_event_id,
                    event_type=event.event_type,
                    case_id=FITBOX_CASE_ID,
                    normalized_event=event,
                    effects={"newly_recognized": True, "case_recovered": True},
                )
            )

        assert len(fake_client.starts) == 1
        _, command, options = fake_client.starts[0]
        assert options == {
            "id": f"recovery-case:{FITBOX_CASE_ID}",
            "task_queue": "recovery-os-test",
        }
        assert command.case_id == FITBOX_CASE_ID
        assert command.candidate_action == "WAIT_FOR_GATEWAY_RETRY"
        assert command.payment_surface_type is None
        assert command.failure_event.payload["payment_state"] == "FAILED"
        assert fake_client.handle.signals == [
            (
                "payment_event",
                PaymentEventSignal(
                    signal_id="razorpay:worker-capture",
                    provider_event_id="evt_worker_capture",
                    payment_state="CAPTURED",
                    amount_paise=149_900,
                    authoritative=True,
                ),
            )
        ]
    finally:
        await engine.dispose()
