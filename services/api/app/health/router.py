"""FastAPI health route contract for containers and deployment probes."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from .checks import run_readiness_checks

router = APIRouter(prefix="/health", tags=["health"])


def _base_payload(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "service": os.getenv("SERVICE_NAME", "recoveryos-api"),
        "version": os.getenv("APP_VERSION", "unknown"),
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("", include_in_schema=False)
@router.get("/live", include_in_schema=False)
async def live() -> dict[str, Any]:
    """Process liveness only; never checks a downstream dependency."""

    return _base_payload("ok")


@router.get("/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    """Return 200 only when PostgreSQL and Temporal are usable."""

    components = await run_readiness_checks()
    is_ready = all(component.status == "ok" for component in components)
    payload = _base_payload("ready" if is_ready else "not_ready")
    payload["components"] = [component.public_dict() for component in components]
    return JSONResponse(status_code=200 if is_ready else 503, content=payload)
