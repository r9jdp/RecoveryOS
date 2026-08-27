from datetime import UTC, datetime, timedelta

from services.api.app.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    FailureKind,
)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 28, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


def test_retryable_failures_open_then_allow_one_half_open_probe() -> None:
    clock = Clock()
    breaker = CircuitBreaker(
        provider="razorpay",
        operation="fetch_payment",
        failure_threshold=2,
        recovery_timeout=timedelta(seconds=20),
        clock=clock,
    )

    assert breaker.before_call().allowed
    assert breaker.record_failure(FailureKind.RETRYABLE) is None
    opened = breaker.record_failure(FailureKind.RETRYABLE)
    assert opened is not None
    assert opened.code == "RAZORPAY_FETCH_PAYMENT_CIRCUIT_OPEN"
    assert opened.retry_after_seconds == 20
    assert opened.automatic_retry_permitted
    assert not breaker.before_call().allowed

    clock.now += timedelta(seconds=20)
    assert breaker.before_call().allowed
    concurrent_probe = breaker.before_call()
    assert not concurrent_probe.allowed
    assert concurrent_probe.reason is not None
    assert concurrent_probe.reason.state == CircuitState.HALF_OPEN
    breaker.record_success()
    assert breaker.state == CircuitState.CLOSED


def test_uncertain_submission_requires_reconciliation_and_never_auto_retries() -> None:
    breaker = CircuitBreaker(provider="twilio", operation="start_contact")
    reason = breaker.record_failure(FailureKind.UNCERTAIN_SUBMISSION)

    assert reason is not None
    assert reason.code == "TWILIO_START_CONTACT_SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED"
    assert reason.requires_reconciliation
    assert not reason.automatic_retry_permitted
    assert reason.retry_after_seconds is None
    assert not breaker.before_call().allowed

    breaker.reconcile_uncertain(provider_confirmed_absent=True)
    assert breaker.state == CircuitState.CLOSED
    assert breaker.before_call().allowed
