"""Clock-injected provider circuit breaker with safe fallback evidence."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum


class CircuitState(StrEnum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class FailureKind(StrEnum):
    RETRYABLE = "RETRYABLE"
    PERMANENT = "PERMANENT"
    UNCERTAIN_SUBMISSION = "UNCERTAIN_SUBMISSION"


@dataclass(frozen=True, slots=True)
class FallbackReason:
    """Machine-readable evidence explaining why a provider action was blocked."""

    code: str
    provider: str
    operation: str
    state: CircuitState
    failure_count: int
    retry_after_seconds: int | None
    requires_reconciliation: bool
    automatic_retry_permitted: bool


@dataclass(frozen=True, slots=True)
class BreakerDecision:
    allowed: bool
    reason: FallbackReason | None = None


class CircuitBreaker:
    """A deterministic circuit breaker for one provider operation.

    Uncertain submissions open immediately and never permit an automatic retry.
    The caller must reconcile the idempotency key with the provider and explicitly
    record success before another submission can be considered.
    """

    def __init__(
        self,
        *,
        provider: str,
        operation: str,
        failure_threshold: int = 3,
        recovery_timeout: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if recovery_timeout <= timedelta(0):
            raise ValueError("recovery_timeout must be positive")
        self.provider = provider.lower()
        self.operation = operation.lower()
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.clock = clock or (lambda: datetime.now(UTC))
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at: datetime | None = None
        self._probe_in_flight = False
        self._uncertain = False

    def before_call(self) -> BreakerDecision:
        now = self._now()
        if self.state == CircuitState.OPEN and not self._uncertain:
            opened_at = self.opened_at
            if opened_at is not None and now - opened_at >= self.recovery_timeout:
                self.state = CircuitState.HALF_OPEN
                self._probe_in_flight = False
        if self.state == CircuitState.CLOSED:
            return BreakerDecision(allowed=True)
        if self.state == CircuitState.HALF_OPEN and not self._probe_in_flight:
            self._probe_in_flight = True
            return BreakerDecision(allowed=True)
        return BreakerDecision(allowed=False, reason=self._fallback_reason(now))

    def record_success(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.opened_at = None
        self._probe_in_flight = False
        self._uncertain = False

    def record_failure(self, kind: FailureKind) -> FallbackReason | None:
        now = self._now()
        self.failure_count += 1
        self._probe_in_flight = False
        if kind == FailureKind.PERMANENT:
            return FallbackReason(
                code=self._code("PERMANENT_REJECTION"),
                provider=self.provider,
                operation=self.operation,
                state=self.state,
                failure_count=self.failure_count,
                retry_after_seconds=None,
                requires_reconciliation=False,
                automatic_retry_permitted=False,
            )
        if kind == FailureKind.UNCERTAIN_SUBMISSION:
            self._uncertain = True
            self._open(now)
            return self._fallback_reason(now)
        if self.state == CircuitState.HALF_OPEN or self.failure_count >= self.failure_threshold:
            self._open(now)
            return self._fallback_reason(now)
        return None

    def reconcile_uncertain(self, *, provider_confirmed_absent: bool) -> None:
        """Resolve an uncertain submission without deciding to retry it.

        A confirmed provider-side result closes the uncertainty circuit. Whether a
        new business action is allowed remains a policy/operator decision upstream.
        """

        if not self._uncertain:
            raise RuntimeError("there is no uncertain submission to reconcile")
        if not provider_confirmed_absent:
            self.record_success()
            return
        self.record_success()

    def _open(self, now: datetime) -> None:
        self.state = CircuitState.OPEN
        self.opened_at = now

    def _fallback_reason(self, now: datetime) -> FallbackReason:
        uncertain = self._uncertain
        retry_after = None
        if not uncertain and self.opened_at is not None:
            remaining = self.recovery_timeout - (now - self.opened_at)
            retry_after = max(0, int(remaining.total_seconds()))
        return FallbackReason(
            code=self._code(
                "SUBMISSION_UNCERTAIN_RECONCILE_REQUIRED" if uncertain else "CIRCUIT_OPEN"
            ),
            provider=self.provider,
            operation=self.operation,
            state=self.state,
            failure_count=self.failure_count,
            retry_after_seconds=retry_after,
            requires_reconciliation=uncertain,
            automatic_retry_permitted=not uncertain,
        )

    def _code(self, suffix: str) -> str:
        return f"{self.provider}_{self.operation}_{suffix}".upper().replace("-", "_")

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("circuit-breaker clock must return a timezone-aware instant")
        return now
