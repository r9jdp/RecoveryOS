from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.app.api import install_core_api
from services.api.app.demo import router as demo_router
from services.api.app.health.router import router as health_router

app = FastAPI(
    title="RecoveryOS API",
    version="0.1.0",
    description="Auditable subscription-recovery orchestration.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip() for origin in os.getenv("WEB_ORIGIN", "http://localhost:3000").split(",")
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(demo_router)
install_core_api(app)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": "recovery-os-api", "status": "ok", "mode": "mock"}
