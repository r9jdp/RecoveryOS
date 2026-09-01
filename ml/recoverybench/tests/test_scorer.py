from pathlib import Path

import pytest

from ml.recoverybench.baseline import RecoveryBenchScorer
from services.api.app.domain.enums import Diagnosis, PaymentSurfaceType, RecoveryActionType
from services.api.app.providers.contracts import RecoveryScoreRequest


def _request(
    surface: PaymentSurfaceType = PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
    diagnosis: Diagnosis = Diagnosis.AUTHENTICATION_REQUIRED,
) -> RecoveryScoreRequest:
    return RecoveryScoreRequest(
        case_id="case_test",
        amount_at_risk_paise=125_000,
        diagnosis=diagnosis,
        candidate_action=RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
        features={
            "tenure_days": 420,
            "prior_successful_payments": 11,
            "failed_attempt_count": 1,
            "customer_agent_available": True,
            "voice_consent": False,
            "is_quiet_hours": False,
            "payment_surface_type": surface.value,
        },
    )


@pytest.mark.asyncio
async def test_missing_artifact_uses_deterministic_fallback(tmp_path: Path) -> None:
    scorer = RecoveryBenchScorer(tmp_path / "absent")

    first = await scorer.score(_request())
    second = await scorer.score(_request())

    assert first == second
    assert first.model_name == "recoverybench-deterministic"
    assert first.expected_recovered_paise == round(
        _request().amount_at_risk_paise * first.recovery_probability
    )


@pytest.mark.asyncio
async def test_checked_in_artifact_scores_with_verified_checksum() -> None:
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts" / "recoverybench.v1"
    result = await RecoveryBenchScorer(artifact_dir).score(_request())

    assert result.model_name == "recoverybench-catboost"
    assert result.model_version == "recoverybench.v1"
    assert result.artifact_checksum
    assert 0 <= result.recovery_probability <= 1
    assert isinstance(result.expected_recovered_paise, int)


@pytest.mark.asyncio
async def test_checked_in_artifact_distinguishes_card_update_from_invoice_link() -> None:
    artifact_dir = Path(__file__).resolve().parents[1] / "artifacts" / "recoverybench.v1"
    scorer = RecoveryBenchScorer(artifact_dir, allow_deterministic_fallback=False)

    card_update = await scorer.score(
        _request(
            PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
            Diagnosis.INSUFFICIENT_FUNDS,
        )
    )
    invoice_link = await scorer.score(
        _request(
            PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
            Diagnosis.INSUFFICIENT_FUNDS,
        )
    )
    authentication_card = await scorer.score(
        _request(
            PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
            Diagnosis.AUTHENTICATION_REQUIRED,
        )
    )
    authentication_invoice = await scorer.score(
        _request(
            PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
            Diagnosis.AUTHENTICATION_REQUIRED,
        )
    )

    assert card_update.model_name == "recoverybench-catboost"
    assert invoice_link.model_name == "recoverybench-catboost"
    assert invoice_link.recovery_probability > card_update.recovery_probability
    assert invoice_link.expected_utility_paise > card_update.expected_utility_paise
    assert authentication_card.recovery_probability > authentication_invoice.recovery_probability
    assert (
        authentication_card.expected_utility_paise > authentication_invoice.expected_utility_paise
    )
