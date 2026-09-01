from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from services.api.app.main import app


def test_dashboard_fixture_is_available_in_local_mock_mode(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
    response = TestClient(app).get("/v1/demo/fixtures/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_version"] == "screens.v1"
    assert payload["evidence_kind"] == "SIMULATED"


def test_dashboard_fixture_is_hidden_from_hosted_provider_mode(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PAYMENT_PROVIDER", "razorpay")

    response = TestClient(app).get("/v1/demo/fixtures/dashboard")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DEMO_MODE_DISABLED"
