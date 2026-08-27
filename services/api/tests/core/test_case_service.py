"""End-to-end core service state convergence tests."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.domain.enums import (
    ActionStatus,
    CaseOutcome,
    PaymentState,
    RevenueAttribution,
)
from services.api.app.models import RecoveryCase, RecoveryEventRecord, RevenueRecognitionRecord
from services.api.app.repositories import CaseFilters, CaseRepository
from services.api.app.seed import FITBOX_CASE_ID, seed_fitbox
from services.api.app.services.cases import RecoveryCaseService
from services.api.app.services.mock_payment import MockPaymentProvider


def service_for(session: AsyncSession) -> RecoveryCaseService:
    return RecoveryCaseService(CaseRepository(session), MockPaymentProvider())


async def test_mock_vertical_slice_and_duplicate_success_are_idempotent(
    session: AsyncSession,
) -> None:
    await seed_fitbox(session)
    service = service_for(session)

    aggregate = await service.get_case(merchant_id="merchant_fitbox", case_id=FITBOX_CASE_ID)
    assert aggregate.latest_action is not None
    action = await service.approve_action(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        action_id=aggregate.latest_action.id,
    )
    assert action.status == ActionStatus.SCHEDULED
    assert action.external_reference is None
    assert action.customer_url is None

    first = await service.apply_mock_payment_success(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        provider_event_id="mock_success_001",
        subscription_reactivated=False,
    )
    duplicate = await service.apply_mock_payment_success(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        provider_event_id="mock_success_001",
        subscription_reactivated=False,
    )

    assert first.newly_recognized is True
    assert duplicate.newly_recognized is False
    assert first.recovery_case.case_outcome == CaseOutcome.RECOVERED
    assert first.recovery_case.payment_state == PaymentState.CAPTURED
    assert first.recovery_case.arrears_collected_paise == 149_900
    assert first.recovery_case.subscription_reactivated is False
    assert first.recovery_case.revenue_attribution == RevenueAttribution.SIMULATED
    recognition_count = await session.scalar(select(func.count(RevenueRecognitionRecord.id)))
    assert recognition_count == 1
    dashboard = await service.dashboard(merchant_id="merchant_fitbox")
    assert dashboard.metrics["revenue_at_risk_paise"] == 0
    assert dashboard.metrics["simulated_incremental_recovery_paise"] == 0
    assert dashboard.metrics["net_recovered_value_paise"] == 0


async def test_out_of_order_failure_is_audited_without_state_regression(
    session: AsyncSession,
) -> None:
    await seed_fitbox(session)
    service = service_for(session)
    await service.apply_mock_payment_success(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        provider_event_id="mock_success_first",
        occurred_at=datetime(2026, 8, 27, 10, 5, tzinfo=UTC),
    )

    inserted = await service.apply_late_failure_event(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        provider_event_id="mock_failure_delivered_late",
        occurred_at=datetime(2026, 8, 27, 9, 59, tzinfo=UTC),
    )
    duplicate = await service.apply_late_failure_event(
        merchant_id="merchant_fitbox",
        case_id=FITBOX_CASE_ID,
        provider_event_id="mock_failure_delivered_late",
        occurred_at=datetime(2026, 8, 27, 9, 59, tzinfo=UTC),
    )

    aggregate = await service.get_case(merchant_id="merchant_fitbox", case_id=FITBOX_CASE_ID)
    assert inserted is True
    assert duplicate is False
    assert aggregate.recovery_case.payment_state == PaymentState.CAPTURED
    assert aggregate.recovery_case.case_outcome == CaseOutcome.RECOVERED
    event_count = await session.scalar(
        select(func.count(RecoveryEventRecord.id)).where(
            RecoveryEventRecord.source_event_id == "mock_failure_delivered_late"
        )
    )
    assert event_count == 1
    timeline = await service.timeline(merchant_id="merchant_fitbox", case_id=FITBOX_CASE_ID)
    assert [event.occurred_at for event in timeline] == sorted(
        event.occurred_at for event in timeline
    )


async def test_list_dashboard_and_recommendation_are_stable(session: AsyncSession) -> None:
    await seed_fitbox(session)
    service = service_for(session)

    page = await service.list_cases(
        merchant_id="merchant_fitbox",
        filters=CaseFilters(),
        cursor=None,
        limit=25,
    )
    dashboard = await service.dashboard(merchant_id="merchant_fitbox")
    first_action, first_policy = await service.recommend_action(
        merchant_id="merchant_fitbox", case_id=FITBOX_CASE_ID
    )
    repeated_action, repeated_policy = await service.recommend_action(
        merchant_id="merchant_fitbox", case_id=FITBOX_CASE_ID
    )

    assert [item.id for item in page.items] == [FITBOX_CASE_ID]
    assert page.has_more is False
    assert dashboard.metrics["revenue_at_risk_paise"] == 149_900
    assert dashboard.metrics["active_cases"] == 1
    assert first_action.id == repeated_action.id
    assert first_policy.id == repeated_policy.id


async def test_dashboard_at_risk_uses_remaining_open_arrears(session: AsyncSession) -> None:
    await seed_fitbox(session)
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    assert recovery_case is not None
    recovery_case.arrears_collected_paise = 49_900
    await session.commit()

    dashboard = await service_for(session).dashboard(merchant_id="merchant_fitbox")

    assert dashboard.metrics["revenue_at_risk_paise"] == 100_000


async def test_dashboard_at_risk_includes_remaining_partially_recovered_arrears(
    session: AsyncSession,
) -> None:
    await seed_fitbox(session)
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    assert recovery_case is not None
    recovery_case.case_outcome = CaseOutcome.PARTIALLY_RECOVERED
    recovery_case.arrears_collected_paise = 49_900
    await session.commit()

    dashboard = await service_for(session).dashboard(merchant_id="merchant_fitbox")

    assert dashboard.metrics["revenue_at_risk_paise"] == 100_000
    assert dashboard.metrics["active_cases"] == 1


async def test_dashboard_verified_gross_uses_immutable_recognition_evidence(
    session: AsyncSession,
) -> None:
    await seed_fitbox(session)
    recovery_case = await session.get(RecoveryCase, FITBOX_CASE_ID)
    assert recovery_case is not None
    recognized_at = datetime(2026, 8, 27, 10, 5, tzinfo=UTC)

    # Mutable case attribution is deliberately opposite to the recognition rows:
    # dashboard accounting must classify each immutable recognition independently.
    recovery_case.revenue_attribution = RevenueAttribution.SIMULATED
    session.add_all(
        [
            RevenueRecognitionRecord(
                id="recognition_test_verified",
                case_id=FITBOX_CASE_ID,
                merchant_id="merchant_fitbox",
                provider="razorpay",
                provider_event_id="event_test_verified",
                amount_paise=30_000,
                attribution=RevenueAttribution.RAZORPAY_TEST_VERIFIED,
                arrears_collected=True,
                subscription_reactivated=False,
                recognized_at=recognized_at,
            ),
            RevenueRecognitionRecord(
                id="recognition_external_verified",
                case_id=FITBOX_CASE_ID,
                merchant_id="merchant_fitbox",
                provider="external",
                provider_event_id="event_external_verified",
                amount_paise=20_000,
                attribution=RevenueAttribution.VERIFIED_EXTERNAL,
                arrears_collected=True,
                subscription_reactivated=False,
                recognized_at=recognized_at,
            ),
            RevenueRecognitionRecord(
                id="recognition_simulated",
                case_id=FITBOX_CASE_ID,
                merchant_id="merchant_fitbox",
                provider="mock",
                provider_event_id="event_simulated",
                amount_paise=90_000,
                attribution=RevenueAttribution.SIMULATED,
                arrears_collected=True,
                subscription_reactivated=False,
                recognized_at=recognized_at,
            ),
            RevenueRecognitionRecord(
                id="recognition_not_arrears",
                case_id=FITBOX_CASE_ID,
                merchant_id="merchant_fitbox",
                provider="external",
                provider_event_id="event_not_arrears",
                amount_paise=10_000,
                attribution=RevenueAttribution.VERIFIED_EXTERNAL,
                arrears_collected=False,
                subscription_reactivated=True,
                recognized_at=recognized_at,
            ),
        ]
    )
    await session.commit()

    dashboard = await service_for(session).dashboard(merchant_id="merchant_fitbox")

    assert dashboard.metrics["verified_recovered_revenue_paise"] == 50_000
    assert dashboard.metrics["simulated_incremental_recovery_paise"] == 0
    # No persisted intervention-cost ledger exists, so recorded cost is zero.
    assert dashboard.metrics["net_recovered_value_paise"] == 50_000


async def test_dashboard_duplicate_recognition_is_counted_once(session: AsyncSession) -> None:
    await seed_fitbox(session)
    repository = CaseRepository(session)
    recognized_at = datetime(2026, 8, 27, 10, 5, tzinfo=UTC)

    def recognition(record_id: str) -> RevenueRecognitionRecord:
        return RevenueRecognitionRecord(
            id=record_id,
            case_id=FITBOX_CASE_ID,
            merchant_id="merchant_fitbox",
            provider="razorpay",
            provider_event_id="event_duplicate",
            amount_paise=25_000,
            attribution=RevenueAttribution.RAZORPAY_TEST_VERIFIED,
            arrears_collected=True,
            subscription_reactivated=False,
            recognized_at=recognized_at,
        )

    assert await repository.recognize_revenue_once(recognition("recognition_first")) is True
    assert await repository.recognize_revenue_once(recognition("recognition_duplicate")) is False
    await repository.commit()

    dashboard = await service_for(session).dashboard(merchant_id="merchant_fitbox")

    assert dashboard.metrics["verified_recovered_revenue_paise"] == 25_000
    assert dashboard.metrics["net_recovered_value_paise"] == 25_000
