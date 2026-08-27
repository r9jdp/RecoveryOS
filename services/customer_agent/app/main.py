from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="RecoveryOS Customer Agent", version="0.1.0")


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "alive"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready"}
