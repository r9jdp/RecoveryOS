from __future__ import annotations

import pytest

from services.api.app.integrations.razorpay.errors import RazorpayIntegrationError
from services.api.app.integrations.razorpay.factory import create_razorpay_client_from_env


def test_factory_requires_server_side_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

    with pytest.raises(RazorpayIntegrationError) as caught:
        create_razorpay_client_from_env()

    assert caught.value.code == "RAZORPAY_CREDENTIALS_NOT_CONFIGURED"


def test_factory_rejects_live_keys_when_test_mode_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_forbidden")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "server-secret")
    monkeypatch.setenv("RAZORPAY_TEST_MODE_REQUIRED", "true")

    with pytest.raises(RazorpayIntegrationError) as caught:
        create_razorpay_client_from_env()

    assert caught.value.code == "RAZORPAY_TEST_MODE_REQUIRED"


async def test_factory_builds_test_client_and_uses_first_allowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "server-secret")
    monkeypatch.setenv("RAZORPAY_TEST_MODE_REQUIRED", "true")
    monkeypatch.setenv("WEB_ORIGIN", "https://app.example,https://preview.example")

    client = create_razorpay_client_from_env()
    try:
        assert client.config.checkout_origin == "https://app.example"
        assert client.config.key_id == "rzp_test_example"
    finally:
        await client.aclose()
