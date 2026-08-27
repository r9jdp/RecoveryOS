import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from services.api.app.domain.enums import PaymentState, SubscriptionState
from services.api.app.integrations.razorpay.models import (
    CorrelationKind,
    ProviderStateCursor,
)
from services.api.app.integrations.razorpay.normalizer import (
    normalize_webhook,
    reduce_provider_state,
)

FIXTURES = Path("services/api/tests/fixtures/razorpay")


def _fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def test_fixture_matrix_normalizes_independent_state_axes() -> None:
    manifest = _fixture("manifest.json")
    items = cast(list[dict[str, str]], manifest["fixtures"])
    for item in items:
        event = normalize_webhook(
            provider_event_id=item["provider_event_id"],
            payload=_fixture(item["file"]),
        )
        assert event.payment_state.value == item["expected_payment_state"]
        assert event.subscription_state.value == item["expected_subscription_state"]


def test_pending_does_not_invent_payment_or_invoice() -> None:
    event = normalize_webhook(
        provider_event_id="evt_pending", payload=_fixture("subscription.pending.json")
    )
    assert event.subscription_id == "sub_fitbox_annual_001"
    assert event.invoice_id is None
    assert event.payment_id is None
    assert event.correlation_kind == CorrelationKind.SUBSCRIPTION_ONLY
    assert event.requires_authoritative_fetch is False


def test_payment_link_requires_notes_correlation_and_reconciliation() -> None:
    event = normalize_webhook(
        provider_event_id="evt_link", payload=_fixture("payment_link.paid.json")
    )
    assert event.case_id == "case_fitbox_aug_2026"
    assert event.invoice_id == "inv_fitbox_aug_2026"
    assert event.payment_state == PaymentState.CAPTURED
    assert (
        event.correlation_kind
        == CorrelationKind.CASE_AND_INVOICE_FROM_NOTES_REQUIRES_RECONCILIATION
    )
    assert event.requires_authoritative_fetch is True


def test_out_of_order_failure_never_regresses_captured_payment() -> None:
    captured = normalize_webhook(
        provider_event_id="evt_captured", payload=_fixture("payment.captured.json")
    )
    failed = normalize_webhook(
        provider_event_id="evt_failed", payload=_fixture("payment.failed.json")
    )
    state = reduce_provider_state(ProviderStateCursor(), captured)
    state = reduce_provider_state(state, failed)
    assert state.payment_state == PaymentState.CAPTURED
    assert state.payment_observed_at == captured.occurred_at

    later_failure = failed.model_copy(update={"occurred_at": datetime(2030, 1, 1, tzinfo=UTC)})
    state = reduce_provider_state(state, later_failure)
    assert state.payment_state == PaymentState.CAPTURED


def test_subscription_axis_has_its_own_event_clock() -> None:
    pending = normalize_webhook(
        provider_event_id="evt_pending", payload=_fixture("subscription.pending.json")
    )
    charged = normalize_webhook(
        provider_event_id="evt_charged", payload=_fixture("subscription.charged.json")
    )
    state = reduce_provider_state(ProviderStateCursor(), charged)
    state = reduce_provider_state(state, pending)
    assert state.subscription_state == SubscriptionState.ACTIVE
