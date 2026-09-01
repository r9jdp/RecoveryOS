"""Runtime-mode guards that keep bundled demo data out of hosted provider paths."""

from __future__ import annotations

import os

from fastapi import HTTPException, status

_LOCAL_DEMO_ENVIRONMENTS = frozenset({"development", "test", "demo", "local"})


def app_environment() -> str:
    """Return the normalized deployment environment."""

    return os.getenv("APP_ENV", "development").strip().lower()


def payment_provider_mode() -> str:
    """Select mock only for local/demo environments; hosted config must be explicit."""

    configured = os.getenv("PAYMENT_PROVIDER", "").strip().lower()
    if configured:
        return configured
    if app_environment() in _LOCAL_DEMO_ENVIRONMENTS:
        return "mock"
    return ""


def demo_mode_enabled() -> bool:
    """Return whether bundled fixtures and mock mutation routes are allowed."""

    configured = os.getenv("DEMO_MODE")
    enabled_by_config = configured is None or configured.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return (
        enabled_by_config
        and app_environment() in _LOCAL_DEMO_ENVIRONMENTS
        and payment_provider_mode() == "mock"
    )


def require_demo_mode() -> None:
    """Hide demo-only HTTP surfaces from hosted or real-provider deployments."""

    if demo_mode_enabled():
        return
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "DEMO_MODE_DISABLED",
            "message": "Bundled demo data is not available in this deployment mode.",
        },
    )


def ensure_demo_seed_allowed() -> None:
    """Prevent the FitBox CLI seed from writing into a hosted/provider database."""

    if demo_mode_enabled():
        return
    raise RuntimeError(
        "The FitBox seed is restricted to APP_ENV=development/test/demo with "
        "PAYMENT_PROVIDER=mock."
    )
