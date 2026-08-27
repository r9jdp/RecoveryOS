"""Hosted-origin-ready FastAPI entry point for the customer A2A agent."""

from __future__ import annotations

from typing import Annotated

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .cards import RECOVERY_MANDATE_EXTENSION_URI, customer_agent_card
from .config import CustomerAgentSettings
from .models import (
    ApprovalDecision,
    CancelTaskParams,
    GetTaskParams,
    JsonRpcRequest,
    SendMessageParams,
)
from .service import CustomerAgentService, TaskConflictError, TaskNotFoundError
from .signing import MandateSigner
from .store import InMemoryTaskStore


def create_app(settings: CustomerAgentSettings | None = None) -> FastAPI:
    active_settings = settings or CustomerAgentSettings()
    signer = MandateSigner.from_seed(
        signer_key_id=active_settings.signer_key_id,
        seed=active_settings.signing_seed(),
    )
    service = CustomerAgentService(
        store=InMemoryTaskStore(),
        signer=signer,
        mandate_ttl_seconds=active_settings.request_ttl_seconds,
    )
    app = FastAPI(
        title="RecoveryOS Customer Authorization Agent",
        version="0.1.0",
        description="A2A service for explicit, exact-surface customer authorization.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[active_settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "A2A-Version", "A2A-Extensions"],
    )
    app.state.customer_agent_service = service

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "live", "service": "recoveryos-customer-agent"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> dict[str, str]:
        mode = "real" if active_settings.real_signing_enabled else "mock"
        return {"status": "ready", "mode": mode}

    @app.get("/.well-known/agent-card.json", tags=["a2a"])
    async def agent_card() -> dict[str, object]:
        return customer_agent_card(
            origin=active_settings.origin,
            signer_key_id=signer.signer_key_id,
            public_key=signer.public_key_base64,
        )

    @app.post("/rpc", tags=["a2a"])
    async def json_rpc(
        request: JsonRpcRequest,
        a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
        a2a_extensions: Annotated[str | None, Header(alias="A2A-Extensions")] = None,
    ) -> JSONResponse:
        if a2a_version != "1.0":
            return _rpc_error(
                request.id,
                -32008,
                "A2A protocol version is not supported",
                [{"supportedVersions": ["1.0"]}],
            )
        declared_extensions = {
            value.strip() for value in (a2a_extensions or "").split(",") if value.strip()
        }
        if RECOVERY_MANDATE_EXTENSION_URI not in declared_extensions:
            return _rpc_error(
                request.id,
                -32009,
                "Recovery mandate extension support is required",
                [{"uri": RECOVERY_MANDATE_EXTENSION_URI}],
            )
        try:
            if request.method == "SendMessage":
                send_params = SendMessageParams.model_validate(request.params)
                task = await service.send_message(send_params.message)
                result = {"task": task.public_dict()}
            elif request.method == "GetTask":
                get_params = GetTaskParams.model_validate(request.params)
                task = await service.get_task(get_params.id)
                result = task.public_dict(history_length=get_params.history_length)
            else:
                cancel_params = CancelTaskParams.model_validate(request.params)
                task = await service.cancel_task(cancel_params.id, reason=cancel_params.reason)
                result = task.public_dict()
        except ValidationError as exc:
            return _rpc_error(request.id, -32602, "Invalid params", exc.errors(include_url=False))
        except TaskNotFoundError:
            return _rpc_error(request.id, -32001, "Task not found")
        except TaskConflictError as exc:
            return _rpc_error(request.id, -32002, str(exc))
        return JSONResponse({"jsonrpc": "2.0", "id": request.id, "result": result})

    @app.get("/v1/tasks/{task_id}/approval", tags=["customer-approval"])
    async def approval_summary(task_id: str) -> dict[str, object]:
        try:
            summary = await service.approval_summary(task_id)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return summary.model_dump(mode="json")

    @app.post("/v1/tasks/{task_id}/approval", tags=["customer-approval"])
    async def approval_decision(task_id: str, decision: ApprovalDecision) -> dict[str, object]:
        try:
            task = await service.decide(task_id=task_id, decision=decision)
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        except TaskConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return task.public_dict()

    return app


def _rpc_error(
    request_id: str | int,
    code: int,
    message: str,
    data: object | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error})


app = create_app()
