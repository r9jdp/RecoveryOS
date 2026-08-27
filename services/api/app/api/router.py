"""Merchant-facing recovery routes, exported for coordinator registration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.db.session import get_async_session
from services.api.app.domain.enums import CaseOutcome, Diagnosis, SubscriptionState
from services.api.app.repositories import CaseFilters, CaseRepository, InvalidCursorError
from services.api.app.services.cases import ApplicationServiceError, RecoveryCaseService
from services.api.app.services.mock_payment import MockPaymentProvider

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
    MockPaymentSuccessRequest,
    MockPaymentSuccessResponse,
    MockPaymentSurfaceRequest,
    PageResponse,
    RecentEventResponse,
    RecommendActionRequest,
    RecoveryCaseResponse,
    RejectActionRequest,
    TimelineEventResponse,
    TimelineResponse,
)

router = APIRouter(prefix="/v1", tags=["recovery"])


def get_merchant_scope() -> str:
    """Return the server-selected merchant for the Phase 1 shared demo login."""

    return "merchant_fitbox"


def get_case_service(
    session: Annotated[AsyncSession, Depends(get_async_session)],
) -> RecoveryCaseService:
    return RecoveryCaseService(CaseRepository(session), MockPaymentProvider())


Service = Annotated[RecoveryCaseService, Depends(get_case_service)]
MerchantScope = Annotated[str, Depends(get_merchant_scope)]


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


ExceptionHandler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def install_core_api(app: FastAPI) -> None:
    """Register routes and required structured error handlers on an application."""

    app.include_router(router)
    app.add_exception_handler(ApplicationServiceError, application_error_handler)
    app.add_exception_handler(InvalidCursorError, validation_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)


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
    "/recovery-cases/{case_id}/actions/recommend",
    response_model=ActionDecisionResponse,
    status_code=201,
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
)
async def approve_recovery_action(
    case_id: str,
    action_id: str,
    service: Service,
    merchant_id: MerchantScope,
) -> ActionResponse:
    action = await service.approve_action(
        merchant_id=merchant_id, case_id=case_id, action_id=action_id
    )
    return ActionResponse.model_validate(action)


@router.post(
    "/recovery-cases/{case_id}/actions/{action_id}/reject",
    response_model=ActionResponse,
)
async def reject_recovery_action(
    case_id: str,
    action_id: str,
    request: RejectActionRequest,
    service: Service,
    merchant_id: MerchantScope,
) -> ActionResponse:
    action = await service.reject_action(
        merchant_id=merchant_id,
        case_id=case_id,
        action_id=action_id,
        reason=request.reason,
    )
    return ActionResponse.model_validate(action)


@router.post("/recovery-cases/{case_id}/stop", response_model=RecoveryCaseResponse)
async def stop_recovery_case(
    case_id: str,
    request: CaseCommandRequest,
    service: Service,
    merchant_id: MerchantScope,
) -> RecoveryCaseResponse:
    recovery_case = await service.stop_case(
        merchant_id=merchant_id, case_id=case_id, reason=request.reason
    )
    return RecoveryCaseResponse.model_validate(recovery_case)


@router.post("/recovery-cases/{case_id}/escalate", response_model=RecoveryCaseResponse)
async def escalate_recovery_case(
    case_id: str,
    request: CaseCommandRequest,
    service: Service,
    merchant_id: MerchantScope,
) -> RecoveryCaseResponse:
    recovery_case = await service.escalate_case(
        merchant_id=merchant_id, case_id=case_id, reason=request.reason
    )
    return RecoveryCaseResponse.model_validate(recovery_case)


@router.post(
    "/mock/recovery-cases/{case_id}/payment-surfaces",
    response_model=ActionResponse,
)
async def open_mock_payment_surface(
    case_id: str,
    request: MockPaymentSurfaceRequest,
    service: Service,
    merchant_id: MerchantScope,
) -> ActionResponse:
    """Explicit mock endpoint mirroring approval-triggered surface creation."""

    action = await service.approve_action(
        merchant_id=merchant_id,
        case_id=case_id,
        action_id=request.action_id,
    )
    return ActionResponse.model_validate(action)


@router.post(
    "/mock/recovery-cases/{case_id}/payment-success",
    response_model=MockPaymentSuccessResponse,
)
async def apply_mock_payment_success(
    case_id: str,
    request: MockPaymentSuccessRequest,
    service: Service,
    merchant_id: MerchantScope,
) -> MockPaymentSuccessResponse:
    result = await service.apply_mock_payment_success(
        merchant_id=merchant_id,
        case_id=case_id,
        provider_event_id=request.provider_event_id,
        amount_paise=request.amount_paise,
        occurred_at=request.occurred_at,
        subscription_reactivated=request.subscription_reactivated,
    )
    return MockPaymentSuccessResponse(
        case=RecoveryCaseResponse.model_validate(result.recovery_case),
        newly_recognized=result.newly_recognized,
    )
