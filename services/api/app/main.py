from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.api.app.demo import router as demo_router
from services.api.app.health.router import router as health_router

app = FastAPI(
    title="RecoveryOS API",
    version="0.1.0",
    description="Auditable subscription-recovery orchestration.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(demo_router)


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"service": "recovery-os-api", "status": "ok", "mode": "mock"}
