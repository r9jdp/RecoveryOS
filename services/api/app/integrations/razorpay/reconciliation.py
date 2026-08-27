"""Late-success convergence using authoritative Razorpay reads."""

from services.api.app.domain.enums import PaymentState, SubscriptionState
from services.api.app.providers.contracts import PaymentSnapshot

from .errors import RazorpayContractError
from .models import NormalizedRazorpayEvent, PaymentRecoveryOutcome


def reconcile_payment_success(
    *,
    event: NormalizedRazorpayEvent,
    snapshot: PaymentSnapshot,
    current_payment_state: PaymentState,
) -> PaymentRecoveryOutcome:
    """Convert an authoritative capture into independent accounting/lifecycle effects."""

    if not snapshot.authoritative or snapshot.provider != "razorpay":
        raise RazorpayContractError(
            "RAZORPAY_RECONCILIATION_NOT_AUTHORITATIVE",
            "Payment success requires an authoritative Razorpay fetch.",
        )
    invoice_id = snapshot.invoice_id or event.invoice_id
    if invoice_id is None:
        raise RazorpayContractError(
            "RAZORPAY_RECONCILIATION_INVOICE_MISSING",
            "Payment success cannot be attributed without an invoice.",
        )
    if event.invoice_id and snapshot.invoice_id and event.invoice_id != snapshot.invoice_id:
        raise RazorpayContractError(
            "RAZORPAY_RECONCILIATION_INVOICE_MISMATCH",
            "Webhook and authoritative payment refer to different invoices.",
        )
    captured = snapshot.payment_state == PaymentState.CAPTURED
    reactivated = snapshot.subscription_state == SubscriptionState.ACTIVE
    return PaymentRecoveryOutcome(
        provider_event_id=event.provider_event_id,
        payment_id=snapshot.payment_id or event.payment_id,
        invoice_id=invoice_id,
        subscription_id=snapshot.subscription_id or event.subscription_id,
        authoritative_payment_state=snapshot.payment_state,
        authoritative_subscription_state=snapshot.subscription_state,
        amount_paise=snapshot.amount_paise,
        arrears_collected=captured,
        subscription_reactivated=reactivated,
        late_success=captured and current_payment_state != PaymentState.CAPTURED,
        should_close_case=captured,
    )
