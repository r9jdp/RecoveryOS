"""Deterministic projection for webhook duplication and reordering tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from services.api.app.domain.enums import PaymentState
from services.api.app.simulator.failure_scenarios import SimulatedDelivery


@dataclass(frozen=True, slots=True)
class DeliveryEffect:
    provider_event_id: str
    duplicate: bool
    stale: bool
    payment_state: PaymentState
    revenue_recorded: bool


@dataclass(slots=True)
class PaymentEventProjection:
    """Converge delivery-order evidence onto authoritative payment state."""

    payment_state: PaymentState = PaymentState.UNKNOWN
    arrears_collected_paise: int = 0
    _latest_occurred_at: datetime | None = None
    _provider_event_ids: set[str] = field(default_factory=set)
    _recognized_payment_ids: set[str] = field(default_factory=set)

    def apply(self, delivery: SimulatedDelivery) -> DeliveryEffect:
        if delivery.provider_event_id in self._provider_event_ids:
            return DeliveryEffect(
                provider_event_id=delivery.provider_event_id,
                duplicate=True,
                stale=False,
                payment_state=self.payment_state,
                revenue_recorded=False,
            )
        self._provider_event_ids.add(delivery.provider_event_id)
        stale = (
            self._latest_occurred_at is not None and delivery.occurred_at < self._latest_occurred_at
        )
        if not stale:
            self._latest_occurred_at = delivery.occurred_at

        authoritative = delivery.authoritative_payment_state
        if self.payment_state != PaymentState.CAPTURED or authoritative == PaymentState.CAPTURED:
            self.payment_state = authoritative

        payment_id = str(delivery.payload["payment_id"])
        revenue_recorded = False
        if (
            authoritative == PaymentState.CAPTURED
            and payment_id not in self._recognized_payment_ids
        ):
            self._recognized_payment_ids.add(payment_id)
            amount_paise = delivery.payload["amount_paise"]
            if isinstance(amount_paise, bool) or not isinstance(amount_paise, int):
                raise TypeError("amount_paise must be an integer")
            self.arrears_collected_paise += amount_paise
            revenue_recorded = True
        return DeliveryEffect(
            provider_event_id=delivery.provider_event_id,
            duplicate=False,
            stale=stale,
            payment_state=self.payment_state,
            revenue_recorded=revenue_recorded,
        )

    @property
    def revenue_entries(self) -> int:
        return len(self._recognized_payment_ids)
