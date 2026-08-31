"""Deployment merchant scope must follow server configuration, never demo constants."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services.api.app.api.router import get_merchant_scope


def test_hosted_razorpay_uses_configured_merchant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RECOVERY_MERCHANT_ID", "recoveryos_test")

    assert get_merchant_scope() == "recoveryos_test"


def test_hosted_razorpay_fails_without_merchant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.delenv("RECOVERY_MERCHANT_ID", raising=False)

    with pytest.raises(HTTPException) as error:
        get_merchant_scope()

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "MERCHANT_SCOPE_NOT_CONFIGURED"


def test_hosted_provider_rejects_fitbox_demo_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")
    monkeypatch.setenv("RECOVERY_MERCHANT_ID", "merchant_fitbox")

    with pytest.raises(HTTPException) as error:
        get_merchant_scope()

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "DEMO_MERCHANT_NOT_ALLOWED"


def test_local_mock_demo_keeps_fitbox_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    monkeypatch.delenv("RECOVERY_MERCHANT_ID", raising=False)

    assert get_merchant_scope() == "merchant_fitbox"
