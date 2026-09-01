from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.a2a.router import router


def test_recovery_agent_card_declares_json_rpc_interface(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RECOVERY_AGENT_ORIGIN", "https://recovery-agent.example")
    monkeypatch.delenv("RECOVERY_AGENT_A2A_INBOUND_BEARER_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(router)
    card = TestClient(app).get("/.well-known/agent-card.json").json()
    assert card["version"] == "0.1.0"
    assert card["supportedInterfaces"][0]["url"] == "https://recovery-agent.example/a2a/rpc"
    assert card["skills"][0]["id"] == "request-customer-recovery-authorization"
    assert card["securitySchemes"] == {}
    assert card["security"] == []


def test_recovery_agent_card_advertises_configured_bearer_auth(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RECOVERY_AGENT_A2A_INBOUND_BEARER_TOKEN", "inbound-secret")
    app = FastAPI()
    app.include_router(router)

    card = TestClient(app).get("/.well-known/agent-card.json").json()

    assert card["securitySchemes"]["a2aInboundBearer"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "opaque",
        "description": "Bearer credential for inbound A2A delegation.",
    }
    assert card["security"] == [{"a2aInboundBearer": []}]
