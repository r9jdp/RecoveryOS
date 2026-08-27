"""Process-local ownership for provider circuit-breaker state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Lock

from .circuit_breaker import CircuitBreaker


class CircuitBreakerRegistry:
    """Return stable breakers across short-lived adapter instances.

    API dependencies build a provider adapter per request. Keeping breakers in a
    process-level registry prevents that lifecycle from resetting safety state.
    Multi-process deployments should additionally emit breaker telemetry; provider
    idempotency and authoritative reconciliation remain the correctness boundary.
    """

    def __init__(self) -> None:
        self._breakers: dict[tuple[str, str, str], CircuitBreaker] = {}
        self._lock = Lock()

    def get(
        self,
        *,
        provider: str,
        operation: str,
        scope: str,
        failure_threshold: int = 3,
        recovery_timeout: timedelta = timedelta(seconds=30),
        clock: Callable[[], datetime] | None = None,
    ) -> CircuitBreaker:
        key = (provider.casefold(), operation.casefold(), scope)
        with self._lock:
            breaker = self._breakers.get(key)
            if breaker is None:
                breaker = CircuitBreaker(
                    provider=provider,
                    operation=operation,
                    failure_threshold=failure_threshold,
                    recovery_timeout=recovery_timeout,
                    clock=clock,
                )
                self._breakers[key] = breaker
            return breaker


_PROVIDER_BREAKERS = CircuitBreakerRegistry()


def provider_breaker_registry() -> CircuitBreakerRegistry:
    return _PROVIDER_BREAKERS
