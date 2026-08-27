import json
from pathlib import Path

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "razorpay"
SCREEN_ROOT = Path(__file__).parents[4] / "packages" / "contracts" / "fixtures"


def test_webhook_manifest_covers_frozen_event_matrix() -> None:
    manifest = json.loads((FIXTURE_ROOT / "manifest.json").read_text(encoding="utf-8"))
    fixtures = manifest["fixtures"]

    assert {item["event"] for item in fixtures} == {
        "payment.failed",
        "subscription.pending",
        "subscription.halted",
        "subscription.charged",
        "payment.captured",
        "payment_link.paid",
    }
    assert len({item["provider_event_id"] for item in fixtures}) == len(fixtures)

    for item in fixtures:
        payload = json.loads((FIXTURE_ROOT / item["file"]).read_text(encoding="utf-8"))
        assert payload["event"] == item["event"]
        assert payload["entity"] == "event"
        assert payload["payload"]


def test_subscription_pending_fixture_does_not_invent_payment_evidence() -> None:
    payload = json.loads((FIXTURE_ROOT / "subscription.pending.json").read_text(encoding="utf-8"))

    assert payload["contains"] == ["subscription"]
    assert "payment" not in payload["payload"]


def test_payment_link_fixture_has_required_safeguards() -> None:
    payload = json.loads((FIXTURE_ROOT / "payment_link.paid.json").read_text(encoding="utf-8"))
    link = payload["payload"]["payment_link"]["entity"]

    assert link["accept_partial"] is False
    assert link["notify"] == {"sms": False, "email": False}
    assert len(link["reference_id"]) <= 40
    assert link["notes"]["case_id"]
    assert link["notes"]["invoice_id"]


def test_screen_fixture_catalog_is_complete_and_json_parseable() -> None:
    expected = {
        "dashboard.json",
        "case-detail.json",
        "ml-lab.json",
        "customer-voice.json",
        "customer-agent.json",
    }

    assert expected.issubset({path.name for path in SCREEN_ROOT.glob("*.json")})
    for filename in expected:
        payload = json.loads((SCREEN_ROOT / filename).read_text(encoding="utf-8"))
        assert payload["fixture_version"] == "screens.v1"
        assert payload["screen"].startswith("/")
