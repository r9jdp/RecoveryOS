"""Model-ranked recovery decisions with deterministic technical and safety gates.

The scorer is advisory: it ranks every action the deployed system can actually
execute.  Persisted merchant policy remains authoritative and is evaluated only
after ranking, so a model can never bypass an opt-out, dispute, kill switch,
quiet-hours window, payment state, or recovery deadline.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
from services.api.app.domain.models import (
    ActionRecommendation,
    PolicyDecision,
    RejectedAlternative,
)
from services.api.app.providers.contracts import RecoveryScoreRequest, RecoveryScoreResult
from services.api.app.providers.interfaces import RecoveryScorer
from services.api.app.safety import (
    SafetyPolicyConfig,
    SafetyPolicyContext,
    evaluate_safety_policy,
)
from services.api.app.safety.policy import quiet_hours_delay_until

DECISION_ENGINE_VERSION = "recovery-ranking.v1"

# These are capability/relevance constraints, not outcome decisions.  They
# prevent the model from selecting an action which cannot address the observed
# failure or which the current execution path cannot safely perform.
_NON_CUSTOMER_REMEDIABLE_DIAGNOSES = frozenset(
    {Diagnosis.MERCHANT_ERROR, Diagnosis.RISK_OR_COMPLIANCE_BLOCK}
)
_GATEWAY_RETRY_RELEVANT_DIAGNOSES = frozenset(
    {
        Diagnosis.TRANSIENT_RETRYABLE,
        Diagnosis.INSUFFICIENT_FUNDS,
        Diagnosis.UNKNOWN,
    }
)
_SURFACE_PREFERENCE: dict[Diagnosis, PaymentSurfaceType] = {
    Diagnosis.AUTHENTICATION_REQUIRED: PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
    Diagnosis.INSTRUMENT_INVALID: PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
    Diagnosis.INSUFFICIENT_FUNDS: PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
}
_ACTION_TIE_PRIORITY: dict[RecoveryActionType, int] = {
    RecoveryActionType.WAIT_FOR_GATEWAY_RETRY: 0,
    RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE: 10,
    RecoveryActionType.SEND_TO_CUSTOMER_AGENT: 20,
    RecoveryActionType.START_VOICE: 30,
    RecoveryActionType.ESCALATE_TO_HUMAN: 40,
    RecoveryActionType.STOP: 50,
}


def customer_agent_executor_ready() -> bool:
    """Advertise A2A only when the live worker boundary is explicitly configured."""

    if os.getenv("A2A_ENABLED", "false").strip().lower() not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    origin = os.getenv("CUSTOMER_AGENT_ORIGIN", "").strip()
    parsed_origin = urlparse(origin)
    if parsed_origin.scheme not in {"http", "https"} or not parsed_origin.netloc:
        return False
    if (
        os.getenv("APP_ENV", "development").strip().lower() == "production"
        and parsed_origin.scheme != "https"
    ):
        return False
    try:
        public_keys = json.loads(os.getenv("CUSTOMER_AGENT_PUBLIC_KEYS_JSON", "{}"))
    except json.JSONDecodeError:
        return False
    return (
        isinstance(public_keys, dict)
        and bool(public_keys)
        and all(isinstance(key, str) and isinstance(value, str) for key, value in public_keys.items())
        and os.getenv("RECOVERY_AGENT_RECEIPT_SIGNING_MODE", "mock").strip().lower()
        == "configured"
        and bool(os.getenv("RECOVERY_AGENT_RECEIPT_SIGNER_KEY_ID", "").strip())
        and bool(os.getenv("RECOVERY_AGENT_RECEIPT_ED25519_PRIVATE_KEY", "").strip())
    )


@lru_cache(maxsize=1)
def get_default_recovery_scorer() -> RecoveryScorer:
    """Reuse one lazily loaded, checksum-verifying scorer per server process."""

    from ml.recoverybench.baseline import RecoveryBenchScorer

    configured_path = os.getenv("RECOVERYBENCH_ARTIFACT_DIR", "").strip()
    artifact_dir = (
        Path(configured_path)
        if configured_path
        else Path(__file__).resolve().parents[4]
        / "ml"
        / "recoverybench"
        / "artifacts"
        / "recoverybench.v1"
    )
    model_required = os.getenv(
        "RECOVERY_MODEL_REQUIRED",
        "true" if os.getenv("APP_ENV", "development").strip().lower() == "production" else "false",
    ).strip().lower() in {"1", "true", "yes", "on"}
    return RecoveryBenchScorer(
        artifact_dir,
        allow_deterministic_fallback=not model_required,
    )


def _scoring_mode(score: RecoveryScoreResult) -> str:
    """Label deterministic fallback explicitly; never present it as trained ML."""

    if score.model_name == "recoverybench-deterministic" or score.model_version.startswith(
        "deterministic."
    ):
        return "DETERMINISTIC_FALLBACK"
    if score.model_name == "recoverybench-catboost" and score.artifact_checksum:
        return "CHECKSUM_VERIFIED_MODEL"
    return "CUSTOM_SCORER"


@dataclass(frozen=True, slots=True)
class RecoveryDecisionContext:
    """Persisted case state and explicit deployment capabilities used for ranking."""

    case_id: str
    amount_at_risk_paise: int
    diagnosis: Diagnosis
    case_outcome: CaseOutcome
    payment_state: PaymentState
    subscription_state: SubscriptionState
    contact_disposition: ContactDisposition
    recovery_deadline: datetime
    now: datetime
    has_failed_invoice: bool
    active_gateway_retries: bool
    standard_payment_link_available: bool = False
    voice_action_available: bool = False
    voice_consent: bool = False
    voice_destination_available: bool = False
    customer_agent_action_available: bool = False
    customer_agent_available: bool = False
    model_features: dict[str, str | int | float | bool | None] | None = None

    def __post_init__(self) -> None:
        if isinstance(self.amount_at_risk_paise, bool) or self.amount_at_risk_paise < 0:
            raise ValueError("amount_at_risk_paise must be a non-negative integer")
        for field_name, value in (
            ("now", self.now),
            ("recovery_deadline", self.recovery_deadline),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RecoveryActionCandidate:
    action_type: RecoveryActionType
    payment_surface_type: PaymentSurfaceType | None
    technical_reason: str
    tie_priority: int

    @property
    def key(self) -> str:
        surface = self.payment_surface_type.value if self.payment_surface_type else "none"
        return f"{self.action_type.value}:{surface}"


@dataclass(frozen=True, slots=True)
class RankedRecoveryCandidate:
    rank: int
    candidate: RecoveryActionCandidate
    score: RecoveryScoreResult
    policy: PolicyDecision
    selected: bool
    rejection_code: str | None = None
    rejection_reason: str | None = None

    def to_audit_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "action_type": self.candidate.action_type.value,
            "payment_surface_type": (
                self.candidate.payment_surface_type.value
                if self.candidate.payment_surface_type
                else None
            ),
            "technical_reason": self.candidate.technical_reason,
            "recovery_probability": self.score.recovery_probability,
            "expected_recovered_paise": self.score.expected_recovered_paise,
            "expected_utility_paise": self.score.expected_utility_paise,
            "model": {
                "name": self.score.model_name,
                "version": self.score.model_version,
                "artifact_checksum": self.score.artifact_checksum,
                "scoring_mode": _scoring_mode(self.score),
            },
            "explanation": list(self.score.explanation),
            "policy": {
                "disposition": self.policy.disposition.value,
                "decision_code": self.policy.decision_code,
                "reason_codes": list(self.policy.reason_codes),
                "reasons": list(self.policy.reasons),
                "policy_version": self.policy.policy_version,
                "delay_until": (
                    self.policy.delay_until.isoformat() if self.policy.delay_until else None
                ),
            },
            "selected": self.selected,
            "rejection_code": self.rejection_code,
            "rejection_reason": self.rejection_reason,
        }


@dataclass(frozen=True, slots=True)
class RecoveryDecisionResult:
    recommendation: ActionRecommendation
    policy: PolicyDecision
    ranked_candidates: tuple[RankedRecoveryCandidate, ...]
    feature_snapshot: dict[str, str | int | float | bool | None]

    @property
    def selected(self) -> RankedRecoveryCandidate:
        return next(candidate for candidate in self.ranked_candidates if candidate.selected)

    def to_audit_payload(self, *, action_id: str | None = None) -> dict[str, Any]:
        selected = self.selected
        return {
            "decision_engine_version": DECISION_ENGINE_VERSION,
            "action_id": action_id,
            "selection_basis": "MAX_POLICY_ELIGIBLE_EXPECTED_UTILITY",
            "selected_rank": selected.rank,
            "selected_action_type": selected.candidate.action_type.value,
            "selected_payment_surface_type": (
                selected.candidate.payment_surface_type.value
                if selected.candidate.payment_surface_type
                else None
            ),
            "selected_expected_recovered_paise": selected.score.expected_recovered_paise,
            "selected_expected_utility_paise": selected.score.expected_utility_paise,
            "selected_model": {
                "name": selected.score.model_name,
                "version": selected.score.model_version,
                "artifact_checksum": selected.score.artifact_checksum,
                "scoring_mode": _scoring_mode(selected.score),
            },
            "feature_snapshot": dict(self.feature_snapshot),
            "ranked_candidates": [item.to_audit_dict() for item in self.ranked_candidates],
            "rejected_alternatives": [
                alternative.model_dump(mode="json")
                for alternative in self.recommendation.rejected_alternatives
            ],
        }


def _surface_candidates(context: RecoveryDecisionContext) -> list[RecoveryActionCandidate]:
    if not context.has_failed_invoice:
        return []
    if context.diagnosis in _NON_CUSTOMER_REMEDIABLE_DIAGNOSES:
        return []
    # A transient pending subscription is already owned by the gateway retry
    # loop.  A second customer-present collection path is not technically safe
    # until that loop resolves; authentication/funding failures remain eligible.
    if context.diagnosis == Diagnosis.TRANSIENT_RETRYABLE and context.active_gateway_retries:
        return []

    surfaces = [
        PaymentSurfaceType.SUBSCRIPTION_CARD_UPDATE,
        PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK,
    ]
    if context.standard_payment_link_available:
        surfaces.append(PaymentSurfaceType.STANDARD_PAYMENT_LINK)
    preferred = _SURFACE_PREFERENCE.get(
        context.diagnosis, PaymentSurfaceType.SUBSCRIPTION_INVOICE_LINK
    )
    surfaces.sort(key=lambda surface: (surface != preferred, surface.value))
    return [
        RecoveryActionCandidate(
            action_type=RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE,
            payment_surface_type=surface,
            technical_reason="A trusted failed invoice is available for this bounded surface.",
            tie_priority=_ACTION_TIE_PRIORITY[
                RecoveryActionType.OPEN_CUSTOMER_PAYMENT_SURFACE
            ]
            + index,
        )
        for index, surface in enumerate(surfaces)
    ]


def generate_technically_eligible_actions(
    context: RecoveryDecisionContext,
) -> tuple[RecoveryActionCandidate, ...]:
    """Enumerate every action supported by the case and deployed capabilities."""

    candidates: list[RecoveryActionCandidate] = []
    if (
        context.active_gateway_retries
        and context.diagnosis in _GATEWAY_RETRY_RELEVANT_DIAGNOSES
    ):
        candidates.append(
            RecoveryActionCandidate(
                RecoveryActionType.WAIT_FOR_GATEWAY_RETRY,
                None,
                "The provider owns an active subscription retry.",
                _ACTION_TIE_PRIORITY[RecoveryActionType.WAIT_FOR_GATEWAY_RETRY],
            )
        )
    candidates.extend(_surface_candidates(context))
    customer_remediable = context.diagnosis not in _NON_CUSTOMER_REMEDIABLE_DIAGNOSES
    if (
        customer_remediable
        and context.voice_action_available
        and context.voice_consent
        and context.voice_destination_available
    ):
        candidates.append(
            RecoveryActionCandidate(
                RecoveryActionType.START_VOICE,
                None,
                "The deployed voice executor has consent and a tokenized destination.",
                _ACTION_TIE_PRIORITY[RecoveryActionType.START_VOICE],
            )
        )
    if (
        customer_remediable
        and context.customer_agent_action_available
        and context.customer_agent_available
    ):
        candidates.append(
            RecoveryActionCandidate(
                RecoveryActionType.SEND_TO_CUSTOMER_AGENT,
                None,
                "The customer-agent executor is available for this customer.",
                _ACTION_TIE_PRIORITY[RecoveryActionType.SEND_TO_CUSTOMER_AGENT],
            )
        )
    candidates.extend(
        [
            RecoveryActionCandidate(
                RecoveryActionType.ESCALATE_TO_HUMAN,
                None,
                "Human review is always available as a non-customer-facing control.",
                _ACTION_TIE_PRIORITY[RecoveryActionType.ESCALATE_TO_HUMAN],
            ),
            RecoveryActionCandidate(
                RecoveryActionType.STOP,
                None,
                "Stopping automation is always technically available.",
                _ACTION_TIE_PRIORITY[RecoveryActionType.STOP],
            ),
        ]
    )
    return tuple(candidates)


class RecoveryDecisionEngine:
    """Score all candidates, rank by integer-paise utility, then apply policy."""

    def __init__(self, scorer: RecoveryScorer) -> None:
        self.scorer = scorer

    async def decide(
        self,
        context: RecoveryDecisionContext,
        policy_config: SafetyPolicyConfig,
    ) -> RecoveryDecisionResult:
        candidates = generate_technically_eligible_actions(context)
        if not candidates:
            raise RuntimeError("decision engine generated no technically eligible action")
        features = self._feature_snapshot(context, policy_config)
        scores = await asyncio.gather(
            *(
                self.scorer.score(
                    RecoveryScoreRequest(
                        case_id=context.case_id,
                        amount_at_risk_paise=context.amount_at_risk_paise,
                        diagnosis=context.diagnosis,
                        candidate_action=candidate.action_type,
                        features={
                            **features,
                            "payment_surface_type": (
                                candidate.payment_surface_type.value
                                if candidate.payment_surface_type
                                else None
                            ),
                        },
                    )
                )
                for candidate in candidates
            )
        )
        for score in scores:
            if score.expected_recovered_paise > context.amount_at_risk_paise:
                raise ValueError("scorer expected recovery exceeds the amount at risk")

        ranked_pairs = sorted(
            zip(candidates, scores, strict=True),
            key=lambda item: (
                -item[1].expected_utility_paise,
                -item[1].expected_recovered_paise,
                -item[1].recovery_probability,
                item[0].tie_priority,
                item[0].key,
            ),
        )
        policies = [
            evaluate_safety_policy(
                SafetyPolicyContext(
                    now=context.now,
                    recovery_deadline=context.recovery_deadline,
                    case_outcome=context.case_outcome,
                    payment_state=context.payment_state,
                    subscription_state=context.subscription_state,
                    contact_disposition=context.contact_disposition,
                    action=candidate.action_type,
                    payment_surface_type=candidate.payment_surface_type,
                    amount_at_risk_paise=context.amount_at_risk_paise,
                    active_gateway_retries=context.active_gateway_retries,
                ),
                policy_config,
            ).to_contract()
            for candidate, _ in ranked_pairs
        ]
        # Policy is deliberately the final gate. Walk the model ranking and
        # choose the highest-utility candidate that deterministic policy does
        # not block. Blocked higher-ranked candidates remain fully auditable.
        selected_index = next(
            index
            for index, policy in enumerate(policies)
            if policy.disposition != PolicyDisposition.BLOCK
        )
        selected_candidate, selected_score = ranked_pairs[selected_index]
        selected_policy = policies[selected_index]
        rejected: list[RejectedAlternative] = []
        ranked: list[RankedRecoveryCandidate] = []
        for index, ((candidate, score), policy) in enumerate(
            zip(ranked_pairs, policies, strict=True), start=1
        ):
            selected = index == selected_index + 1
            rejection_code: str | None = None
            rejection_reason: str | None = None
            if not selected:
                if policy.disposition == PolicyDisposition.BLOCK:
                    rejection_code = policy.decision_code
                    rejection_reason = policy.reasons[0]
                elif score.expected_utility_paise == selected_score.expected_utility_paise:
                    rejection_code = "STABLE_TIE_BREAK"
                    rejection_reason = (
                        "Expected utility tied; the stable, auditable tie-break selected "
                        f"{selected_candidate.key}."
                    )
                else:
                    rejection_code = "LOWER_EXPECTED_UTILITY"
                    utility_gap = (
                        selected_score.expected_utility_paise - score.expected_utility_paise
                    )
                    rejection_reason = (
                        f"Expected utility was {utility_gap} paise below the selected candidate."
                    )
                rejected.append(
                    RejectedAlternative(
                        action=candidate.action_type,
                        payment_surface_type=candidate.payment_surface_type,
                        reason_code=rejection_code,
                        reason=rejection_reason,
                    )
                )
            ranked.append(
                RankedRecoveryCandidate(
                    rank=index,
                    candidate=candidate,
                    score=score,
                    policy=policy,
                    selected=selected,
                    rejection_code=rejection_code,
                    rejection_reason=rejection_reason,
                )
            )

        recommendation = ActionRecommendation(
            action=selected_candidate.action_type,
            payment_surface_type=selected_candidate.payment_surface_type,
            predicted_recovery_probability=selected_score.recovery_probability,
            expected_recovered_paise=selected_score.expected_recovered_paise,
            expected_utility_paise=selected_score.expected_utility_paise,
            confidence=selected_score.recovery_probability,
            reason_codes=[
                (
                    "DETERMINISTIC_FALLBACK_MAX_POLICY_ELIGIBLE_UTILITY"
                    if _scoring_mode(selected_score) == "DETERMINISTIC_FALLBACK"
                    else "MODEL_MAX_POLICY_ELIGIBLE_EXPECTED_UTILITY"
                ),
                *selected_policy.reason_codes,
            ],
            reasons=[*selected_score.explanation, *selected_policy.reasons],
            rejected_alternatives=rejected,
        )
        return RecoveryDecisionResult(
            recommendation=recommendation,
            policy=selected_policy,
            ranked_candidates=tuple(ranked),
            feature_snapshot=features,
        )

    @staticmethod
    def _feature_snapshot(
        context: RecoveryDecisionContext,
        policy_config: SafetyPolicyConfig,
    ) -> dict[str, str | int | float | bool | None]:
        is_quiet_hours = False
        if (
            policy_config.quiet_hours_start is not None
            and policy_config.quiet_hours_end is not None
        ):
            is_quiet_hours = (
                quiet_hours_delay_until(
                    context.now,
                    timezone_name=policy_config.merchant_timezone,
                    start=policy_config.quiet_hours_start,
                    end=policy_config.quiet_hours_end,
                )
                is not None
            )
        return {
            **(context.model_features or {}),
            "amount_at_risk_paise": context.amount_at_risk_paise,
            "diagnosis": context.diagnosis.value,
            "customer_agent_available": context.customer_agent_available,
            "voice_consent": context.voice_consent,
            "is_quiet_hours": is_quiet_hours,
            "subscription_state": context.subscription_state.value,
            "payment_state": context.payment_state.value,
            "contact_disposition": context.contact_disposition.value,
            "active_gateway_retries": context.active_gateway_retries,
        }
