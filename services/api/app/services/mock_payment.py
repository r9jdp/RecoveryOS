"""Deterministic mock payment surface used by the default demo mode."""

from __future__ import annotations

import hashlib
from urllib.parse import quote

from services.api.app.providers.contracts import (
    OpenPaymentSurfaceRequest,
    PaymentSnapshot,
    PaymentSurfaceResult,
)


class MockPaymentProvider:
    """Side-effect-free implementation of the frozen PaymentProvider port."""

    async def open_customer_payment_surface(
        self, request: OpenPaymentSurfaceRequest
    ) -> PaymentSurfaceResult:
        digest = hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:16]
        reference = f"mock_surface_{digest}"
        return PaymentSurfaceResult(
            provider="mock",
            provider_reference=reference,
            surface_type=request.surface_type,
            customer_url=f"https://demo.recoveryos.local/pay/{quote(reference)}",
            expires_at=request.expires_at,
            authoritative=False,
        )

    async def fetch_payment_snapshot(
        self, *, merchant_id: str, payment_id: str | None, invoice_id: str
    ) -> PaymentSnapshot:
        raise NotImplementedError(
            "mock snapshots are applied through the explicit success endpoint"
        )
