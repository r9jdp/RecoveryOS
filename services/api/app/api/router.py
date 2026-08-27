"""Merchant-facing recovery routes, exported for coordinator registration."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Header, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.db.session import get_async_session
from services.api.app.domain.enums import (
    CaseOutcome,
    ContactDisposition,
    Diagnosis,
    SubscriptionState,
)
from services.api.app.integrations.razorpay import create_razorpay_client_from_env
from services.api.app.integrations.razorpay.errors import RazorpayIntegrationError
from services.api.app.models import Merchant, MerchantPolicySetting
from services.api.app.providers.interfaces import PaymentProvider
from services.api.app.repositories import CaseFilters, CaseRepository, InvalidCursorError
from services.api.app.services.cases import (
    ApplicationServiceError,
    CaseNotFoundError,
    RecoveryCaseService,
)
from services.api.app.services.mock_payment import MockPaymentProvider
from services.api.app.simulator import FailureScenario, build_failure_scenario
from services.api.app.webhooks.razorpay import RazorpayWebhookIngestionService
from services.api.app.webhooks.repository import InboxOutboxStore
from services.api.app.workflows import (
    RecoveryWorkflowCommander,
    get_recovery_workflow_commander,
)

from .operator_auth import require_operator_for_non_mock_payment
from .schemas import (
    ActionDecisionResponse,
    ActionResponse,
    CaseCommandRequest,
    CaseDetailResponse,
    CaseListResponse,
    CaseSummaryResponse,
    DashboardMetricsResponse,
    DashboardResponse,
    DiagnosisBucketResponse,
    FailureSimulationRequest,
    FailureSimulationResponse,
    MockPaymentSuccessRequest,
    MockPaymentSuccessResponse,
    MockPaymentSurfaceRequest,
    OperatorCommandRequest,
    OperatorCommandResponse,
    PageResponse,
    PolicySettingsResponse,
    PolicySettingsUpdate,
    RazorpayWebhookAckResponse,
    RecentEventResponse,
    RecommendActionRequest,
    RecoveryCaseResponse,
    RejectActionRequest,
    SafetyDispositionRequest,
    SafetyDispositionResponse,
    TimelineEventResponse,
    TimelineResponse,
)

router = APIRouter(prefix="/v1", tags=["recovery"])


def get_merchant_scope() -> str:
    """Return the server-selected merchant for the Phase 1 shared demo login."""

    return "merchant_fitbox"


async def get_payment_provider() -> AsyncIterator[PaymentProvider]:
    provider = os.getenv("PAYMENT_PROVIDER", "mock").strip().lower()
    if provider == "mock":
        yield MockPaymentProvider()
        return
    if provider != "razorpay":
        raise RazorpayIntegrationError(
            "PAYMENT_PROVIDER_UNSUPPORTED",
            "PAYMENT_PROVIDER must be mock or razorpay.",
            status_code=503,
        )
    client = create_razorpay_client_from_env()
    try:
        yield client
    finally:
        await client.aclose()


def get_case_service(
    session: Annotated[AsyncSession, Depends(get_async_session)],
    payment_provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
) -> RecoveryCaseService:
    return RecoveryCaseService(
        CaseRepository(session),
        payment_provider,
        global_kill_switch=(
            os.getenv("RECOVERY_GLOBAL_KILL_SWITCH", "false").strip().lower() == "true"
        ),
    )


Service = Annotated[RecoveryCaseService, Depends(get_case_service)]
MerchantScope = Annotated[str, Depends(get_merchant_scope)]
Session = Annotated[AsyncSession, Depends(get_async_session)]
WorkflowCommander = Annotated[RecoveryWorkflowCommander, Depends(get_recovery_workflow_commander)]


def get_razorpay_webhook_secret() -> str:
    """Resolve the webhook secret exclusively from the server environment."""

    secret = os.getenv("RAZORPAY_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise RazorpayIntegrationError(
            "RAZORPAY_WEBHOOK_NOT_CONFIGURED",
            "Razorpay webhook ingestion is not configured for this environment.",
            status_code=503,
        )
    return secret


RazorpayWebhookSecret = Annotated[str, Depends(get_razorpay_webhook_secret)]


def _request_context(request: Request) -> tuple[str, str]:
    request_id = request.headers.get("X-Request-Id") or f"req_{uuid4().hex}"
    correlation_id = request.headers.get("X-Correlation-Id") or f"corr_{uuid4().hex}"
    return request_id[:128], correlation_id[:128]


async def application_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApplicationServiceError):
        raise exc
    request_id, correlation_id = _request_context(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "field": None,
                "metadata": exc.metadata,
            },
            "request_id": request_id,
            "correlation_id": correlation_id,
        },
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, (RequestValidationError, InvalidCursorError)):
        raise exc
    request_id, correlation_id = _request_context(request)
    if isinstance(exc, RequestValidationError):
        errors = exc.errors()
        field = "/" + "/".join(str(part) for part in errors[0]["loc"]) if errors else None
        message = "Request validation failed."
    else:
        field = "/query/cursor"
        message = str(exc)
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_FAILED",
                "message": message,
                "field": field,
                "metadata": {},
            },
            "request_id": request_id,
            "correlation_id": correlation_id,
        },
    )


async def razorpay_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RazorpayIntegrationError):
        raise exc
    request_id, correlation_id = _request_context(request)
    status_code = exc.status_code or (
        401 if exc.code == "RAZORPAY_WEBHOOK_SIGNATURE_INVALID" else 422
    )
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": str(exc),
                "field": None,
                "metadata": {**exc.metadata, "retriable": exc.retriable},
            },
            "request_id": request_id,
            "correlation_id": correlation_id,
        },
    )


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def install_core_api(app: FastAPI) -> None:
    """Register routes and required structured error handlers on an application."""

    app.include_router(router)
    app.add_exception_handler(ApplicationServiceError, application_error_handler)
    app.add_exception_handler(InvalidCursorError, validation_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(RazorpayIntegrationError, razorpay_error_handler)


@router.post(
    "/webhooks/razorpay",
    response_model=RazorpayWebhookAckResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["razorpay"],
)
async def ingest_razorpay_webhook(
    request: Request,
    session: Session,
    merchant_id: MerchantScope,
    webhook_secret: RazorpayWebhookSecret,
    signature: Annotated[str, Header(alias="X-Razorpay-Signature", min_length=1)],
    provider_event_id: Annotated[str, Header(alias="X-Razorpay-Event-Id", min_length=1)],
) -> RazorpayWebhookAckResponse:
    """Verify the untouched body and atomically enqueue provider processing."""

    receipt = await RazorpayWebhookIngestionService(InboxOutboxStore(session)).ingest(
        merchant_id=merchant_id,
        raw_body=await request.body(),
        signature=signature,
        provider_event_id=provider_event_id,
        webhook_secret=webhook_secret,
    )
    return RazorpayWebhookAckResponse.model_validate(receipt)


def _policy_settings_response(
    merchant: Merchant,
    settings: MerchantPolicySetting,
) -> PolicySettingsResponse:
    return PolicySettingsResponse(
        timezone=merchant.timezone,
        quiet_hours_start=settings.quiet_hours_start,
        quiet_hours_end=settings.quiet_hours_end,
        max_contacts_per_7_days=settings.max_contacts_per_7_days,
        require_approval_above_paise=settings.require_approval_above_paise,
        require_approval_actions=settings.require_approval_actions,
        recovery_kill_switch=settings.recovery_kill_switch,
        version=settings.version,
        updated_at=settings.updated_at,
    )


@router.get("/policy-settings", response_model=PolicySettingsResponse, tags=["policy"])
async def get_policy_settings(
    session: Session,
    merchant_id: MerchantScope,
) -> PolicySettingsResponse:
    merchant = await session.get(Merchant, merchant_id)
    settings = await session.get(MerchantPolicySetting, merchant_id)
    if merchant is None or settings is None:
        raise CaseNotFoundError(
            "Merchant policy settings were not found.", metadata={"merchant_id": merchant_id}
        )
    return _policy_settings_response(merchant, settings)


@router.put(
    "/policy-settings",
    response_model=PolicySettingsResponse,
    tags=["policy"],
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def update_policy_settings(
    request: PolicySettingsUpdate,
    session: Session,
    merchant_id: MerchantScope,
) -> PolicySettingsResponse:
    merchant = await session.scalar(
        select(Merchant).where(Merchant.id == merchant_id).with_for_update()
    )
    settings = await session.scalar(
        select(MerchantPolicySetting)
        .where(MerchantPolicySetting.merchant_id == merchant_id)
        .with_for_update()
    )
    if merchant is None or settings is None:
        raise CaseNotFoundError(
            "Merchant policy settings were not found.", metadata={"merchant_id": merchant_id}
        )
    merchant.timezone = request.timezone
    settings.quiet_hours_start = request.quiet_hours_start
    settings.quiet_hours_end = request.quiet_hours_end
    settings.max_contacts_per_7_days = request.max_contacts_per_7_days
    settings.require_approval_above_paise = request.require_approval_above_paise
    settings.require_approval_actions = [
        action.value for action in request.require_approval_actions
    ]
    settings.recovery_kill_switch = request.recovery_kill_switch
    settings.version += 1
    await session.commit()
    await session.refresh(settings)
    return _policy_settings_response(merchant, settings)


@router.post(
    "/simulations/failure-injection",
    response_model=FailureSimulationResponse,
    tags=["simulation"],
)
async def generate_failure_simulation(
    request: FailureSimulationRequest,
) -> FailureSimulationResponse:
    scenario = build_failure_scenario(
        FailureScenario(request.scenario),
        seed=request.seed,
        amount_paise=request.amount_paise,
        evidence_kind=request.evidence_kind,
    )
    return FailureSimulationResponse.model_validate(scenario.to_api_dict())


@router.get("/dashboard/metrics", response_model=DashboardResponse)
async def get_dashboard(service: Service, merchant_id: MerchantScope) -> DashboardResponse:
    snapshot = await service.dashboard(merchant_id=merchant_id)
    return DashboardResponse(
        metrics=DashboardMetricsResponse.model_validate(snapshot.metrics),
        diagnosis_distribution=[
            DiagnosisBucketResponse(diagnosis=diagnosis, case_count=count)
            for diagnosis, count in snapshot.diagnosis_distribution
        ],
        recent_events=[
            RecentEventResponse.model_validate(event) for event in snapshot.recent_events
        ],
    )


@router.get("/recovery-cases", response_model=CaseListResponse)
async def list_recovery_cases(
    service: Service,
    merchant_id: MerchantScope,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: str | None = None,
    case_outcome: Annotated[list[CaseOutcome] | None, Query()] = None,
    diagnosis: Annotated[list[Diagnosis] | None, Query()] = None,
    subscription_state: Annotated[list[SubscriptionState] | None, Query()] = None,
    opened_from: datetime | None = None,
    opened_to: datetime | None = None,
) -> CaseListResponse:
    page = await service.list_cases(
        merchant_id=merchant_id,
        filters=CaseFilters(
            outcomes=tuple(case_outcome or ()),
            diagnoses=tuple(diagnosis or ()),
            subscription_states=tuple(subscription_state or ()),
            opened_from=opened_from,
            opened_to=opened_to,
        ),
        cursor=cursor,
        limit=limit,
    )
    summaries: list[CaseSummaryResponse] = []
    for recovery_case in page.items:
        aggregate = await service.get_case(merchant_id=merchant_id, case_id=recovery_case.id)
        latest_action = aggregate.latest_action
        summaries.append(
            CaseSummaryResponse(
                id=recovery_case.id,
                merchant_id=recovery_case.merchant_id,
                failed_invoice_id=recovery_case.failed_invoice_id,
                billing_cycle_key=recovery_case.billing_cycle_key,
                customer_display_name=aggregate.customer.display_name,
                plan_name=aggregate.subscription.plan_name,
                amount_at_risk_paise=recovery_case.amount_at_risk_paise,
                case_outcome=recovery_case.case_outcome,
                payment_state=recovery_case.payment_state,
                subscription_state=recovery_case.subscription_state,
                contact_disposition=recovery_case.contact_disposition,
                revenue_attribution=recovery_case.revenue_attribution,
                diagnosis=recovery_case.diagnosis,
                recommended_action=latest_action.action_type if latest_action else None,
                payment_surface_type=(
                    latest_action.payment_surface_type if latest_action else None
                ),
                updated_at=recovery_case.updated_at,
            )
        )
    return CaseListResponse(
        items=summaries,
        page=PageResponse(
            next_cursor=page.next_cursor,
            has_more=page.has_more,
            limit=limit,
        ),
    )


@router.get("/recovery-cases/{case_id}", response_model=CaseDetailResponse)
async def get_recovery_case(
    case_id: str, service: Service, merchant_id: MerchantScope
) -> CaseDetailResponse:
    aggregate = await service.get_case(merchant_id=merchant_id, case_id=case_id)
    return CaseDetailResponse(
        case=RecoveryCaseResponse.model_validate(aggregate.recovery_case),
        customer=aggregate.customer,
        subscription=aggregate.subscription,
        invoice=aggregate.invoice,
        payment_failure=aggregate.failed_payment,
        latest_action=aggregate.latest_action,
        latest_policy=aggregate.latest_policy,
        available_commands=["APPROVE", "REJECT", "STOP", "ESCALATE_TO_HUMAN"],
    )


@router.get("/recovery-cases/{case_id}/timeline", response_model=TimelineResponse)
async def get_recovery_case_timeline(
    case_id: str, service: Service, merchant_id: MerchantScope
) -> TimelineResponse:
    events = await service.timeline(merchant_id=merchant_id, case_id=case_id)
    return TimelineResponse(items=[TimelineEventResponse.model_validate(event) for event in events])


@router.post(
    "/recovery-cases/{case_id}/commands",
    response_model=OperatorCommandResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def execute_operator_command(
    case_id: str,
    request: OperatorCommandRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> OperatorCommandResponse:
    """Stable UI command façade over action-specific recovery endpoints."""

    occurred_at = datetime.now(UTC)
    if request.command in {"APPROVE", "REJECT"}:
        aggregate = await service.get_case(merchant_id=merchant_id, case_id=case_id)
        action = aggregate.latest_action
        if action is None:
            action, _ = await service.recommend_action(
                merchant_id=merchant_id,
                case_id=case_id,
                now=occurred_at,
            )
        if request.command == "APPROVE":
            await service.approve_action(
                merchant_id=merchant_id,
                case_id=case_id,
                action_id=action.id,
                now=occurred_at,
            )
            await workflow_commander.approval(
                case_id=case_id,
                action_id=action.id,
                approved=True,
                reason=None,
            )
            message = "Recovery action approved."
        else:
            await service.reject_action(
                merchant_id=merchant_id,
                case_id=case_id,
                action_id=action.id,
                reason="Rejected by the merchant operator.",
                now=occurred_at,
            )
            await workflow_commander.approval(
                case_id=case_id,
                action_id=action.id,
                approved=False,
                reason="Rejected by the merchant operator.",
            )
            message = "Recovery action rejected."
    elif request.command == "STOP":
        await service.stop_case(
            merchant_id=merchant_id,
            case_id=case_id,
            reason="Stopped by the merchant operator.",
            now=occurred_at,
        )
        await workflow_commander.stop(
            case_id=case_id,
            reason="Stopped by the merchant operator.",
        )
        message = "Recovery case stopped."
    else:
        await service.escalate_case(
            merchant_id=merchant_id,
            case_id=case_id,
            reason="Escalated by the merchant operator.",
            now=occurred_at,
        )
        await workflow_commander.escalate(
            case_id=case_id,
            reason="Escalated by the merchant operator.",
        )
        message = "Recovery case escalated to human review."
    return OperatorCommandResponse(
        command=request.command, message=message, occurred_at=occurred_at
    )


@router.post(
    "/recovery-cases/{case_id}/safety-dispositions",
    response_model=SafetyDispositionResponse,
    tags=["policy"],
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def record_safety_disposition(
    case_id: str,
    request: SafetyDispositionRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> SafetyDispositionResponse:
    occurred_at = datetime.now(UTC)
    if request.disposition == "ESCALATE_TO_HUMAN":
        recovery_case = await service.escalate_case(
            merchant_id=merchant_id,
            case_id=case_id,
            reason="Escalated by the merchant operator from the safety controls.",
            now=occurred_at,
        )
        await workflow_commander.escalate(
            case_id=case_id,
            reason="Escalated by the merchant operator from the safety controls.",
        )
        message = "Recovery case escalated to human review."
    else:
        dispositions = {
            "MARK_DISPUTE": ContactDisposition.DISPUTE,
            "MARK_OPT_OUT": ContactDisposition.OPTED_OUT,
            "MARK_ALREADY_PAID": ContactDisposition.ALREADY_PAID,
            "MARK_WRONG_PERSON": ContactDisposition.WRONG_PERSON,
        }
        contact_disposition = dispositions[request.disposition]
        recovery_case = await service.record_safety_disposition(
            merchant_id=merchant_id,
            case_id=case_id,
            disposition=contact_disposition,
            now=occurred_at,
        )
        messages = {
            ContactDisposition.DISPUTE: "Dispute recorded; automated recovery was stopped.",
            ContactDisposition.OPTED_OUT: "Opt-out recorded; future outreach was suppressed.",
            ContactDisposition.ALREADY_PAID: (
                "Already-paid report recorded; recovery was stopped for reconciliation."
            ),
            ContactDisposition.WRONG_PERSON: (
                "Wrong-person report recorded; future outreach was suppressed."
            ),
        }
        message = messages[contact_disposition]
    return SafetyDispositionResponse(
        disposition=request.disposition,
        message=message,
        occurred_at=occurred_at,
        case=RecoveryCaseResponse.model_validate(recovery_case),
    )


@router.post(
    "/recovery-cases/{case_id}/actions/recommend",
    response_model=ActionDecisionResponse,
    status_code=201,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def recommend_recovery_action(
    case_id: str,
    request: RecommendActionRequest,
    service: Service,
    merchant_id: MerchantScope,
) -> ActionDecisionResponse:
    action, policy = await service.recommend_action(
        merchant_id=merchant_id,
        case_id=case_id,
        action_type=request.action_type,
        payment_surface_type=request.payment_surface_type,
    )
    return ActionDecisionResponse(action=action, policy=policy)


@router.post(
    "/recovery-cases/{case_id}/actions/{action_id}/approve",
    response_model=ActionResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def approve_recovery_action(
    case_id: str,
    action_id: str,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> ActionResponse:
    await service.get_action_for_command(
        merchant_id=merchant_id, case_id=case_id, action_id=action_id
    )
    action = await service.approve_action(
        merchant_id=merchant_id, case_id=case_id, action_id=action_id
    )
    await workflow_commander.approval(
        case_id=case_id,
        action_id=action_id,
        approved=True,
        reason=None,
    )
    return ActionResponse.model_validate(action)


@router.post(
    "/recovery-cases/{case_id}/actions/{action_id}/reject",
    response_model=ActionResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def reject_recovery_action(
    case_id: str,
    action_id: str,
    request: RejectActionRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> ActionResponse:
    await service.get_action_for_command(
        merchant_id=merchant_id, case_id=case_id, action_id=action_id
    )
    action = await service.reject_action(
        merchant_id=merchant_id,
        case_id=case_id,
        action_id=action_id,
        reason=request.reason,
    )
    await workflow_commander.approval(
        case_id=case_id,
        action_id=action_id,
        approved=False,
        reason=request.reason,
    )
    return ActionResponse.model_validate(action)


@router.post(
    "/recovery-cases/{case_id}/stop",
    response_model=RecoveryCaseResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def stop_recovery_case(
    case_id: str,
    request: CaseCommandRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> RecoveryCaseResponse:
    await service.get_case(merchant_id=merchant_id, case_id=case_id)
    recovery_case = await service.stop_case(
        merchant_id=merchant_id, case_id=case_id, reason=request.reason
    )
    await workflow_commander.stop(case_id=case_id, reason=request.reason)
    return RecoveryCaseResponse.model_validate(recovery_case)


@router.post(
    "/recovery-cases/{case_id}/escalate",
    response_model=RecoveryCaseResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def escalate_recovery_case(
    case_id: str,
    request: CaseCommandRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> RecoveryCaseResponse:
    await service.get_case(merchant_id=merchant_id, case_id=case_id)
    recovery_case = await service.escalate_case(
        merchant_id=merchant_id, case_id=case_id, reason=request.reason
    )
    await workflow_commander.escalate(case_id=case_id, reason=request.reason)
    return RecoveryCaseResponse.model_validate(recovery_case)


@router.post(
    "/mock/recovery-cases/{case_id}/payment-surfaces",
    response_model=ActionResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def open_mock_payment_surface(
    case_id: str,
    request: MockPaymentSurfaceRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> ActionResponse:
    """Explicit mock endpoint mirroring approval-triggered surface creation."""

    await service.get_action_for_command(
        merchant_id=merchant_id,
        case_id=case_id,
        action_id=request.action_id,
    )
    action = await service.approve_action(
        merchant_id=merchant_id,
        case_id=case_id,
        action_id=request.action_id,
    )
    await workflow_commander.approval(
        case_id=case_id,
        action_id=request.action_id,
        approved=True,
        reason=None,
    )
    return ActionResponse.model_validate(action)


@router.post(
    "/mock/recovery-cases/{case_id}/payment-success",
    response_model=MockPaymentSuccessResponse,
    dependencies=[Depends(require_operator_for_non_mock_payment)],
)
async def apply_mock_payment_success(
    case_id: str,
    request: MockPaymentSuccessRequest,
    service: Service,
    merchant_id: MerchantScope,
    workflow_commander: WorkflowCommander,
) -> MockPaymentSuccessResponse:
    result = await service.apply_mock_payment_success(
        merchant_id=merchant_id,
        case_id=case_id,
        provider_event_id=request.provider_event_id,
        amount_paise=request.amount_paise,
        occurred_at=request.occurred_at,
        subscription_reactivated=request.subscription_reactivated,
    )
    await workflow_commander.payment_captured(
        case_id=case_id,
        provider_event_id=request.provider_event_id,
        amount_paise=result.recognized_amount_paise,
    )
    return MockPaymentSuccessResponse(
        case=RecoveryCaseResponse.model_validate(result.recovery_case),
        newly_recognized=result.newly_recognized,
    )
