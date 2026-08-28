from __future__ import annotations

import pytest

from services.api.app.services.mock_payment import MockPaymentProvider
from services.worker.app.activities import MockRecoveryActivityServices
from services.worker.app.runtime import (
    ActivityConfigurationError,
    ProductionRecoveryActivityServices,
    create_activity_services_from_env,
)


def test_activity_factory_defaults_to_safe_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RECOVERY_ACTIVITY_MODE", raising=False)
    assert isinstance(create_activity_services_from_env(), MockRecoveryActivityServices)


def test_production_mock_wiring_requires_database_and_is_persistence_backed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOVERY_ACTIVITY_MODE", "production")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ActivityConfigurationError, match="DATABASE_URL"):
        create_activity_services_from_env()

    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    assert isinstance(create_activity_services_from_env(), ProductionRecoveryActivityServices)


def test_razorpay_wiring_is_guarded_before_credentials_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RECOVERY_ACTIVITY_MODE", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://configured")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.delenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", raising=False)
    with pytest.raises(ActivityConfigurationError, match="RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS"):
        create_activity_services_from_env()

    monkeypatch.setenv("RECOVERY_ALLOW_REAL_PAYMENT_ACTIONS", "true")
    monkeypatch.setenv("RAZORPAY_TEST_MODE_REQUIRED", "false")
    with pytest.raises(ActivityConfigurationError, match="production-mode keys"):
        create_activity_services_from_env()

    selected: list[str] = []

    def selected_razorpay_client() -> MockPaymentProvider:
        selected.append("razorpay")
        return MockPaymentProvider()

    monkeypatch.setenv("RAZORPAY_TEST_MODE_REQUIRED", "true")
    monkeypatch.setattr(
        "services.worker.app.runtime.create_razorpay_client_from_env",
        selected_razorpay_client,
    )
    assert isinstance(create_activity_services_from_env(), ProductionRecoveryActivityServices)
    assert selected == ["razorpay"]
