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
from services.api.app.models import RecoveryEventRecord, RevenueRecognitionRecord
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
    assert action.status == ActionStatus.SUCCEEDED
    assert action.external_reference is not None
    assert action.customer_url is not None

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
