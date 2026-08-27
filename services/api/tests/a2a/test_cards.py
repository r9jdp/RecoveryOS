from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.a2a.router import router


def test_recovery_agent_card_declares_json_rpc_interface(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("RECOVERY_AGENT_ORIGIN", "https://recovery-agent.example")
    app = FastAPI()
    app.include_router(router)
    card = TestClient(app).get("/.well-known/agent-card.json").json()
    assert card["version"] == "0.1.0"
    assert card["supportedInterfaces"][0]["url"] == "https://recovery-agent.example/a2a/rpc"
    assert card["skills"][0]["id"] == "request-customer-recovery-authorization"
