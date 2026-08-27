from fastapi.testclient import TestClient

from services.api.app.main import app


def test_dashboard_fixture_is_available() -> None:
    response = TestClient(app).get("/v1/demo/fixtures/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["fixture_version"] == "screens.v1"
    assert payload["evidence_kind"] == "SIMULATED"
