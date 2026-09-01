from __future__ import annotations

import os

from fastapi import FastAPI

from services.api.app.a2a import router as a2a_router
from services.api.app.api import install_core_api
from services.api.app.demo import router as demo_router
from services.api.app.embedded_worker import lifespan
from services.api.app.health.router import router as health_router
from services.api.app.http_security import install_credentialed_cors
from services.api.app.lab import install_lab_api
from services.api.app.razorpay_onboarding import router as razorpay_onboarding_router
from services.api.app.voice import router as voice_router

app = FastAPI(
    title="RecoveryOS API",
    version="0.1.0",
    description="Auditable subscription-recovery orchestration.",
    lifespan=lifespan,
)
install_credentialed_cors(
    app,
    os.getenv("WEB_ORIGIN", "http://localhost:3000"),
)
app.include_router(health_router)
app.include_router(demo_router)
install_core_api(app)
install_lab_api(app)
app.include_router(razorpay_onboarding_router)
app.include_router(voice_router)
app.include_router(a2a_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str | bool]:
    return {
        "service": "recovery-os-api",
        "status": "ok",
        "environment": os.getenv("APP_ENV", "development"),
        "payment_provider": os.getenv("PAYMENT_PROVIDER", "mock").strip().lower(),
        "recovery_activity_mode": os.getenv("RECOVERY_ACTIVITY_MODE", "mock")
        .strip()
        .lower(),
        "a2a_enabled": os.getenv("A2A_ENABLED", "false").strip().lower()
        in {"1", "true", "yes", "on"},
        "voice_provider": os.getenv("VOICE_PROVIDER", "mock").strip().lower(),
    }
