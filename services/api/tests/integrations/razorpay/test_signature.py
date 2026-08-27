from pathlib import Path

import pytest

from services.api.app.integrations.razorpay.errors import InvalidWebhookSignatureError
from services.api.app.integrations.razorpay.signature import (
    verify_webhook_signature,
    webhook_signature,
)

FIXTURES = Path("services/api/tests/fixtures/razorpay")


def test_signature_uses_exact_raw_bytes() -> None:
    raw_body = (FIXTURES / "payment.failed.json").read_bytes()
    signature = webhook_signature(raw_body, "test_webhook_secret")

    verify_webhook_signature(raw_body, signature, "test_webhook_secret")

    with pytest.raises(InvalidWebhookSignatureError):
        verify_webhook_signature(raw_body + b"\n", signature, "test_webhook_secret")


@pytest.mark.parametrize("signature,secret", [("", "secret"), ("bad", "secret"), ("bad", "")])
def test_invalid_signature_is_rejected(signature: str, secret: str) -> None:
    with pytest.raises(InvalidWebhookSignatureError) as caught:
        verify_webhook_signature(b"{}", signature, secret)
    assert caught.value.code == "RAZORPAY_WEBHOOK_SIGNATURE_INVALID"
