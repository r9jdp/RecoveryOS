from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.app.lab.router import install_lab_api


def _client() -> TestClient:
    app = FastAPI()
    install_lab_api(app)
    return TestClient(app)


def test_latest_report_is_versioned_simulated_and_read_only() -> None:
    response = _client().get("/v1/lab/reports/latest")

    assert response.status_code == 200
    report = response.json()
    assert report["schema_version"] == "recoverybench.report.v1"
    assert report["dataset"]["evaluation_case_count"] >= 100
    assert report["guardrails"]["label"] == "simulated incremental recovery"
    assert report["guardrails"]["merchant_revenue_mutated"] is False
    assert "verified_recovered_revenue_paise" not in response.text


def test_versioned_report_and_missing_report() -> None:
    client = _client()

    assert client.get("/v1/lab/reports/recoverybench.v1").status_code == 200
    missing = client.get("/v1/lab/reports/recoverybench.v999")
    assert missing.status_code == 404
