from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from services.api.app.http_security import (
    credentialed_web_origins,
    install_credentialed_cors,
)


def test_credentialed_origins_are_exact_normalized_and_deduplicated() -> None:
    assert credentialed_web_origins(
        "https://recovery.example, https://preview.example/,https://recovery.example"
    ) == ["https://recovery.example", "https://preview.example"]


@pytest.mark.parametrize(
    "configured",
    [
        "",
        "*",
        "https://*.example.test",
        "https://user:secret@example.test",
        "https://example.test/dashboard",
        "https://example.test?preview=true",
    ],
)
def test_credentialed_origins_reject_unsafe_values(configured: str) -> None:
    with pytest.raises(RuntimeError, match="WEB_ORIGIN"):
        credentialed_web_origins(configured)


async def test_credentialed_cors_allows_exact_origin_and_csrf_header_only() -> None:
    app = FastAPI()
    install_credentialed_cors(app, "https://recovery.example")

    @app.post("/consequential")
    async def consequential() -> dict[str, bool]:
        return {"accepted": True}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://api.example.test",
    ) as client:
        allowed = await client.options(
            "/consequential",
            headers={
                "Origin": "https://recovery.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-RecoveryOS-CSRF-Token,Content-Type",
            },
        )
        denied = await client.options(
            "/consequential",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-RecoveryOS-CSRF-Token",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "https://recovery.example"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert "x-recoveryos-csrf-token" in allowed.headers["access-control-allow-headers"].lower()
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
