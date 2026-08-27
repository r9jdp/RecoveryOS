"""Isolated RecoveryOS Agent Card router for coordinator registration."""

from __future__ import annotations

import os

from fastapi import APIRouter

router = APIRouter(tags=["a2a"])


@router.get("/.well-known/agent-card.json", include_in_schema=False)
async def recovery_agent_card() -> dict[str, object]:
    origin = os.getenv("RECOVERY_AGENT_ORIGIN", "http://localhost:8000").rstrip("/")
    return {
        "name": "RecoveryOS Recovery Agent",
        "description": (
            "Diagnoses failed subscription payments and requests bounded customer authorization. "
            "Payment execution remains in deterministic provider activities."
        ),
        "supportedInterfaces": [
            {
                "url": f"{origin}/a2a/rpc",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "version": "0.1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extensions": [
                {
                    "uri": "https://recoveryos.dev/a2a/recovery-mandate/v1",
                    "required": True,
                }
            ],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "request-customer-recovery-authorization",
                "name": "Request recovery authorization",
                "description": "Creates an exact recovery.request.v1 DataPart for customer review.",
                "tags": ["recovery", "subscription", "authorization"],
                "inputModes": ["application/json"],
                "outputModes": ["application/json"],
            }
        ],
        "securitySchemes": {},
        "security": [],
    }
