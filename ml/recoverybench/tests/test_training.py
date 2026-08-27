import json
from pathlib import Path

from ml.recoverybench.training import artifact_checksum, train_artifact


def test_checked_in_report_checksum_and_metric_bounds() -> None:
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts" / "recoverybench.v1"
    report = json.loads((artifact_dir / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((artifact_dir / "manifest.json").read_text(encoding="utf-8"))

    assert artifact_checksum(artifact_dir) == manifest["artifact_checksum"]
    assert report["artifact"]["artifact_checksum"] == manifest["artifact_checksum"]
    assert report["dataset"]["evaluation_case_count"] >= 100
    assert report["guardrails"] == {
        "label": "simulated incremental recovery",
        "merchant_revenue_mutated": False,
        "production_artifact_required": False,
    }
    assert 0 <= report["metrics"]["pr_auc"] <= 1
    assert 0 <= report["metrics"]["brier_score"] <= 1
    assert report["metrics"]["top_decile_lift"] >= 0
    assert report["metrics"]["amount_weighted_lift"] >= 0
    assert (
        sum(item["case_count"] for item in report["metrics"]["recovery_by_action"])
        == report["dataset"]["evaluation_case_count"]
    )


def test_training_report_is_reproducible(tmp_path: Path) -> None:
    first = train_artifact(tmp_path / "first", seed=772, case_count=300)
    second = train_artifact(tmp_path / "second", seed=772, case_count=300)

    assert first["metrics"] == second["metrics"]
    assert first["dataset"] == second["dataset"]
    assert first["artifact"]["artifact_checksum"] == artifact_checksum(tmp_path / "first")
    assert second["artifact"]["artifact_checksum"] == artifact_checksum(tmp_path / "second")
