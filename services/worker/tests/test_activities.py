from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from services.worker.app.activities import MockRecoveryActivityServices
from services.worker.app.contracts import (
    CancelActionInput,
    DiagnosisInput,
    ExecuteActionInput,
    NormalizeFailureInput,
    ProviderEvent,
    ReconciliationInput,
    ScoreInput,
)


@pytest.mark.asyncio
async def test_mock_activity_services_are_idempotent_and_reconcile_authoritatively() -> None:
    services = MockRecoveryActivityServices(require_manual_approval=False)
    now = datetime.now(UTC)
    failure = await services.normalize_failure(
        NormalizeFailureInput(
            case_id="case-fitbox",
            merchant_id="merchant-fitbox",
            subscription_id="sub-fitbox",
            failed_invoice_id="inv-fitbox",
            failed_payment_id="pay-fitbox",
            event=ProviderEvent(
                event_id="evt-failed",
                event_type="payment.failed",
                occurred_at=now.isoformat(),
                payload={
                    "payment_state": "FAILED",
                    "subscription_state": "PENDING",
                    "reason_code": "BAD_REQUEST_PAYMENT_CARD_INSUFFICIENT_BALANCE",
                },
            ),
        )
    )
    diagnosis = await services.diagnose_failure(
        DiagnosisInput(case_id="case-fitbox", failure=failure)
    )
    score = await services.score_recovery(
        ScoreInput(
            case_id="case-fitbox",
            amount_at_risk_paise=149_900,
            diagnosis=diagnosis.diagnosis,
            candidate_action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        )
    )

    assert diagnosis.diagnosis == "INSUFFICIENT_FUNDS"
    assert score.expected_recovered_paise == 106_429
    assert score.expected_utility_paise == 104_929

    action = ExecuteActionInput(
        case_id="case-fitbox",
        merchant_id="merchant-fitbox",
        customer_id="customer-fitbox",
        subscription_id="sub-fitbox",
        failed_invoice_id="inv-fitbox",
        amount_paise=149_900,
        currency="INR",
        action="OPEN_CUSTOMER_PAYMENT_SURFACE",
        payment_surface_type="SUBSCRIPTION_INVOICE_LINK",
        recovery_deadline=(now + timedelta(hours=1)).isoformat(),
        idempotency_key="case-fitbox:open:1",
    )
    first = await services.execute_recovery_action(action)
    duplicate = await services.execute_recovery_action(action)
    assert duplicate == first
    assert len(services.executed_actions) == 1

    unverified = await services.reconcile_case(
        ReconciliationInput(
            case_id="case-fitbox",
            merchant_id="merchant-fitbox",
            failed_invoice_id="inv-fitbox",
            failed_payment_id="pay-fitbox",
            trigger_event_id="browser-callback",
            payment_state_hint="CAPTURED",
            amount_paise_hint=149_900,
            authoritative_hint=False,
        )
    )
    verified = await services.reconcile_case(
        ReconciliationInput(
            case_id="case-fitbox",
            merchant_id="merchant-fitbox",
            failed_invoice_id="inv-fitbox",
            failed_payment_id="pay-fitbox",
            trigger_event_id="evt-captured",
            payment_state_hint="CAPTURED",
            amount_paise_hint=149_900,
            authoritative_hint=True,
        )
    )
    assert unverified.case_recovered is False
    assert unverified.arrears_collected_paise == 0
    assert verified.case_recovered is True
    assert verified.arrears_collected_paise == 149_900

    cancel = CancelActionInput(
        case_id="case-fitbox",
        provider_reference=first.provider_reference,
        reason="AUTHORITATIVE_PAYMENT_SUCCESS",
        idempotency_key="case-fitbox:cancel:success",
    )
    assert (await services.cancel_recovery_action(cancel)).cancelled is True
    assert (await services.cancel_recovery_action(cancel)).reason_code == "ALREADY_CANCELLED"
