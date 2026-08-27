"""Async provider ports used by activities and application services."""

from typing import Protocol, runtime_checkable

from .contracts import (
    CustomerAgentRecoveryRequest,
    CustomerAgentTask,
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
    RecoveryScoreRequest,
    RecoveryScoreResult,
    VoiceContactRequest,
    VoiceContactResult,
    VoiceContactSnapshot,
)


@runtime_checkable
class PaymentProvider(Protocol):
    """Open or inspect customer-present payment surfaces.

    This port intentionally has no `retry_payment` or `charge_payment` method.
    Razorpay owns retries for pending subscriptions; RecoveryOS may only wait,
    open a bounded customer surface, and reconcile authoritative provider state.
    """

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult: ...

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot: ...


@runtime_checkable
class VoiceProvider(Protocol):
    async def start_contact(self, request: VoiceContactRequest) -> VoiceContactResult: ...

    async def cancel_contact(self, *, contact_attempt_id: str, reason: str) -> None: ...

    async def fetch_contact(self, *, contact_attempt_id: str) -> VoiceContactSnapshot: ...


@runtime_checkable
class RecoveryScorer(Protocol):
    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult: ...


@runtime_checkable
class CustomerAgentClient(Protocol):
    async def send_recovery_request(
        self, request: CustomerAgentRecoveryRequest
    ) -> CustomerAgentTask: ...

    async def get_task(self, *, remote_task_id: str) -> CustomerAgentTask: ...

    async def cancel_task(self, *, remote_task_id: str, reason: str) -> CustomerAgentTask: ...
