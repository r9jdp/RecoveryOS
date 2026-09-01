"""Multi-candidate recovery ranking and deterministic final-gate tests."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import (
    CaseOutcome,
    ContactDisposition,
    Diagnosis,
    PaymentState,
    PaymentSurfaceType,
    PolicyDisposition,
    RecoveryActionType,
    SubscriptionState,
)
from services.api.app.models import (
    PolicyDecisionRecord,
    RecoveryActionRecord,
    RecoveryEventRecord,
)
from services.api.app.providers.contracts import RecoveryScoreRequest, RecoveryScoreResult
from services.api.app.repositories import CaseRepository
from services.api.app.safety import SafetyPolicyConfig
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.services.cases import RecoveryCaseService
from services.api.app.services.decision_engine import (
    RecoveryDecisionContext,
    RecoveryDecisionEngine,
    generate_technically_eligible_actions,
    get_default_recovery_scorer,
)
from services.api.app.services.mock_payment import MockPaymentProvider

NOW = datetime(2030, 1, 1, 10, 0, tzinfo=UTC)


class MatrixScorer:
    def __init__(self, utilities: dict[str, int]) -> None:
        self.utilities = utilities
        self.requests: list[RecoveryScoreRequest] = []

    async def score(self, request: RecoveryScoreRequest) -> RecoveryScoreResult:
        self.requests.append(request)
        surface = request.features.get("payment_surface_type") or "none"
        key = f"{request.candidate_action.value}:{surface}"
        utility = self.utilities[key]
        recovered = max(min(utility + 1_000, request.amount_at_risk_paise), 0)
        return RecoveryScoreResult(
            model_name="test-catboost",
            model_version="artifact.v7",
            artifact_checksum="abc123",
            recovery_probability=recovered / request.amount_at_risk_paise,
            expected_recovered_paise=recovered,
            expected_utility_paise=utility,
            explanation=[f"matrix score for {key}"],
        )


def context(**overrides: object) -> RecoveryDecisionContext:
    values: dict[str, object] = {
        "case_id": "case_ranked",
        "amount_at_risk_paise": 100_000,
        "diagnosis": Diagnosis.AUTHENTICATION_REQUIRED,
        "case_outcome": CaseOutcome.OPEN,
        "payment_state": PaymentState.FAILED,
        "subscription_state": SubscriptionState.HALTED,
        "contact_disposition": ContactDisposition.NOT_CONTACTED,
        "recovery_deadline": NOW + timedelta(days=3),
        "now": NOW,
        "has_failed_invoice": True,
        "active_gateway_retries": False,
        "model_features": {
            "tenure_days": 420,
            "prior_successful_payments": 11,
            "failed_attempt_count": 2,
        },
    }
    values.update(overrides)
    return RecoveryDecisionContext(**values)  # type: ignore[arg-type]


async def test_scores_every_technical_candidate_and_ranks_integer_paise_utility() -> None:
    scorer = MatrixScorer(
        {
            "OPEN_CUSTOMER_PAYMENT_SURFACE:SUBSCRIPTION_CARD_UPDATE": 30_000,
            "OPEN_CUSTOMER_PAYMENT_SURFACE:SUBSCRIPTION_INVOICE_LINK": 55_000,
            "ESCALATE_TO_HUMAN:none": 12_000,
            "STOP:none": 0,
        }
    )

    result = await RecoveryDecisionEngine(scorer).decide(context(), SafetyPolicyConfig())

    assert len(scorer.requests) == 4
    assert result.recommendation.action == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
    assert (
        result.recommendation.payment_surface_type
        == PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK
    )
    assert result.recommendation.expected_recovered_paise == 56_000
    assert result.recommendation.expected_utility_paise == 55_000
    assert isinstance(result.recommendation.expected_recovered_paise, int)
    assert isinstance(result.recommendation.expected_utility_paise, int)
    assert {request.features["prior_successful_payments"] for request in scorer.requests} == {11}
    assert [candidate.rank for candidate in result.ranked_candidates] == [1, 2, 3, 4]
    assert len(result.recommendation.rejected_alternatives) == 3


async def test_policy_rejects_model_preference_and_selects_highest_safe_fallback() -> None:
    scorer = MatrixScorer(
        {
            "OPEN_CUSTOMER_PAYMENT_SURFACE:SUBSCRIPTION_CARD_UPDATE": 80_000,
            "OPEN_CUSTOMER_PAYMENT_SURFACE:SUBSCRIPTION_INVOICE_LINK": 70_000,
            "ESCALATE_TO_HUMAN:none": 20_000,
            "STOP:none": 10_000,
        }
    )

    result = await RecoveryDecisionEngine(scorer).decide(
        context(), SafetyPolicyConfig(merchant_kill_switch=True)
    )

    assert result.recommendation.action == RecoveryActionType.ESCALATE_TO_HUMAN
    assert result.policy.disposition == PolicyDisposition.ALLOW
    assert result.selected.rank == 3
    assert result.ranked_candidates[0].policy.disposition == PolicyDisposition.BLOCK
    assert result.ranked_candidates[0].rejection_code == "MERCHANT_KILL_SWITCH_ENABLED"
    assert result.ranked_candidates[1].rejection_code == "MERCHANT_KILL_SWITCH_ENABLED"
    audit = result.to_audit_payload(action_id="action_ranked")
    assert audit["selected_model"] == {
        "name": "test-catboost",
        "version": "artifact.v7",
        "artifact_checksum": "abc123",
        "scoring_mode": "CUSTOM_SCORER",
    }
    assert audit["feature_snapshot"]["failed_attempt_count"] == 2
    assert audit["ranked_candidates"][0]["policy"]["decision_code"] == (
        "MERCHANT_KILL_SWITCH_ENABLED"
    )


def test_transient_gateway_retry_excludes_competing_collection_surfaces() -> None:
    candidates = generate_technically_eligible_actions(
        context(
            diagnosis=Diagnosis.TRANSIENT_RETRYABLE,
            subscription_state=SubscriptionState.PENDING,
            active_gateway_retries=True,
        )
    )

    assert [candidate.action_type for candidate in candidates] == [
        RecoveryActionType.WAIT_FOR_GATEWAY_RETRY,
        RecoveryActionType.ESCALATE_TO_HUMAN,
        RecoveryActionType.STOP,
    ]


async def test_deterministic_fallback_is_explicitly_tagged_not_presented_as_ml() -> None:
    from ml.recoverybench.baseline import DeterministicRecoveryScorer

    result = await RecoveryDecisionEngine(DeterministicRecoveryScorer()).decide(
        context(), SafetyPolicyConfig()
    )

    audit = result.to_audit_payload()
    assert audit["selected_model"]["scoring_mode"] == "DETERMINISTIC_FALLBACK"
    assert result.recommendation.reason_codes[0] == (
        "DETERMINISTIC_FALLBACK_MAX_POLICY_ELIGIBLE_UTILITY"
    )


async def test_default_scorer_loads_the_checksum_verified_packaged_artifact() -> None:
    get_default_recovery_scorer.cache_clear()
    scorer = get_default_recovery_scorer()
    result = await scorer.score(
        RecoveryScoreRequest(
            case_id="case_packaged_artifact",
            amount_at_risk_paise=100_000,
            diagnosis=Diagnosis.AUTHENTICATION_REQUIRED,
            candidate_action=RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
            features={
                "tenure_days": 365,
                "prior_successful_payments": 10,
                "failed_attempt_count": 1,
                "customer_agent_available": False,
                "voice_consent": False,
                "is_quiet_hours": False,
            },
        )
    )

    assert result.model_name == "recoverybench-catboost"
    assert result.model_version == "recoverybench.v1"
    assert result.artifact_checksum
    decision = await RecoveryDecisionEngine(scorer).decide(context(), SafetyPolicyConfig())
    assert decision.to_audit_payload()["selected_model"]["scoring_mode"] == (
        "CHECKSUM_VERIFIED_MODEL"
    )


async def test_case_service_persists_ranked_envelope_for_a_new_recommendation(
    session: AsyncSession,
) -> None:
    await seed_fitbox(session)
    await session.execute(
        delete(PolicyDecisionRecord).where(PolicyDecisionRecord.case_id == FITBOX_CASE_ID)
    )
    await session.execute(
        delete(RecoveryActionRecord).where(RecoveryActionRecord.case_id == FITBOX_CASE_ID)
    )
    await session.execute(
        delete(RecoveryEventRecord).where(
            RecoveryEventRecord.case_id == FITBOX_CASE_ID,
            RecoveryEventRecord.event_type == "ACTION_RECOMMENDED",
        )
    )
    await session.commit()
    scorer = MatrixScorer(
        {
            "WAIT_FOR_GATEWAY_RETRY:none": 20_000,
            "OPEN_CUSTOMER_PAYMENT_SURFACE:SUBSCRIPTION_CARD_UPDATE": 60_000,
            "OPEN_CUSTOMER_PAYMENT_SURFACE:SUBSCRIPTION_INVOICE_LINK": 50_000,
            "ESCALATE_TO_HUMAN:none": 10_000,
            "STOP:none": 0,
        }
    )
    service = RecoveryCaseService(
        CaseRepository(session),
        MockPaymentProvider(),
        recovery_scorer=scorer,
    )

    action, policy = await service.recommend_action(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        now=datetime(2026, 8, 28, 10, 0, tzinfo=UTC),
    )

    event = await session.scalar(
        select(RecoveryEventRecord).where(
            RecoveryEventRecord.source_event_id == f"recommendation:{action.id}"
        )
    )
    assert action.action_type == RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
    assert action.payment_surface_type == PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE
    assert policy.disposition == PolicyDisposition.ALLOW
    assert event is not None
    assert event.payload["selected_model"]["name"] == "test-catboost"
    assert event.payload["feature_snapshot"]["failed_attempt_count"] == 1
    assert len(event.payload["ranked_candidates"]) == 4
