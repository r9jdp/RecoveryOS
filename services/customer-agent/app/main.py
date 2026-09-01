"""Hosted-origin-ready FastAPI entry point for the customer A2A agent."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .cards import (
    RECOVERY_MANDATE_EXTENSION_URI,
    RECOVERY_RECEIPT_EXTENSION_URI,
    customer_agent_card,
)
from .config import CustomerAgentSettings
from .llm import (
    CustomerLanguageInterpreter,
    DisabledCustomerLanguageInterpreter,
    LanguageInterpreterNotConfiguredError,
    LanguageInterpreterProviderError,
    LanguageInterpreterTimeoutError,
    OpenAIResponsesLanguageInterpreter,
)
from .models import (
    ApprovalDecision,
    CancelTaskParams,
    CustomerLanguageRequest,
    GetTaskParams,
    JsonRpcRequest,
    SendMessageParams,
)
from .service import CustomerAgentService, TaskConflictError, TaskNotFoundError
from .signing import MandateSigner, ReceiptVerifier
from .store import TaskStore, create_task_store


def create_app(
    settings: CustomerAgentSettings | None = None,
    *,
    task_store: TaskStore | None = None,
    language_interpreter: CustomerLanguageInterpreter | None = None,
) -> FastAPI:
    active_settings = settings or CustomerAgentSettings()
    signer = MandateSigner.from_seed(
        signer_key_id=active_settings.signer_key_id,
        seed=active_settings.signing_seed(),
    )
    recovery_receipt_public_keys = active_settings.recovery_receipt_public_keys()
    store = task_store or create_task_store(
        mode=active_settings.task_store,
        database_url=(
            active_settings.durable_database_url() if active_settings.task_store == "sql" else None
        ),
    )
    interpreter = language_interpreter or _create_language_interpreter(active_settings)
    service = CustomerAgentService(
        store=store,
        signer=signer,
        receipt_verifier=ReceiptVerifier(pinned_public_keys=recovery_receipt_public_keys),
        language_interpreter=interpreter,
        mandate_ttl_seconds=active_settings.request_ttl_seconds,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await interpreter.close()
            await store.close()

    app = FastAPI(
        title="RecoveryOS Customer Authorization Agent",
        version="0.1.0",
        description="A2A service for explicit, exact-surface customer authorization.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[active_settings.web_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "A2A-Version", "A2A-Extensions"],
    )
    app.state.customer_agent_service = service
    app.state.customer_agent_store = store
    app.state.customer_language_interpreter = interpreter

    @app.get("/health/live", tags=["health"])
    async def live() -> dict[str, str]:
        return {"status": "live", "service": "recoveryos-customer-agent"}

    @app.get("/health/ready", tags=["health"])
    async def ready() -> JSONResponse:
        mode = "real" if active_settings.real_signing_enabled else "mock"
        available = await store.is_ready()
        content = {
            "status": "ready" if available else "not_ready",
            "mode": mode,
            "store": store.kind,
        }
        return JSONResponse(content, status_code=200 if available else 503)

    @app.get("/.well-known/agent-card.json", tags=["a2a"])
    async def agent_card() -> dict[str, object]:
        return customer_agent_card(
            origin=active_settings.origin,
            signer_key_id=signer.signer_key_id,
            public_key=signer.public_key_base64,
            accepted_receipt_signer_key_ids=sorted(recovery_receipt_public_keys),
        )

    @app.post("/rpc", tags=["a2a"])
    async def json_rpc(
        http_request: Request,
        a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
        a2a_extensions: Annotated[str | None, Header(alias="A2A-Extensions")] = None,
    ) -> JSONResponse:
        try:
            raw_request = await http_request.json()
        except ValueError:
            return _rpc_error(None, -32700, "Parse error")
        try:
            request = JsonRpcRequest.model_validate(raw_request)
        except ValidationError as exc:
            request_id = (
                raw_request.get("id")
                if isinstance(raw_request, dict) and isinstance(raw_request.get("id"), (str, int))
                else None
            )
            return _rpc_error(
                request_id,
                -32600,
                "Invalid Request",
                exc.errors(include_url=False),
            )
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
        if RECOVERY_RECEIPT_EXTENSION_URI not in declared_extensions:
            return _rpc_error(
                request.id,
                -32009,
                "Authenticated recovery receipt extension support is required",
                [{"uri": RECOVERY_RECEIPT_EXTENSION_URI}],
            )
        if request.method not in {"SendMessage", "GetTask", "CancelTask"}:
            return _rpc_error(request.id, -32601, "Method not found")
        try:
            if request.method == "SendMessage":
                send_params = SendMessageParams.model_validate(request.params)
                task = await service.send_message(send_params.message)
                result = {"task": task.public_dict()}
            elif request.method == "GetTask":
                get_params = GetTaskParams.model_validate(request.params)
                task = await service.get_task(get_params.id)
                result = task.public_dict(history_length=get_params.history_length)
            elif request.method == "CancelTask":
                cancel_params = CancelTaskParams.model_validate(request.params)
                task = await service.cancel_task(cancel_params.id, reason=cancel_params.reason)
                result = task.public_dict()
            else:  # Defensive guard for future dispatch edits.
                return _rpc_error(request.id, -32601, "Method not found")
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

    @app.post("/v1/tasks/{task_id}/interpretation", tags=["customer-approval"])
    async def interpret_customer_language(
        task_id: str,
        request: CustomerLanguageRequest,
    ) -> dict[str, object]:
        try:
            interpretation = await service.interpret_customer_language(
                task_id=task_id,
                request=request,
            )
        except TaskNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        except TaskConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except LanguageInterpreterNotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except LanguageInterpreterTimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
        except LanguageInterpreterProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return interpretation.model_dump(mode="json")

    return app


def _create_language_interpreter(
    settings: CustomerAgentSettings,
) -> CustomerLanguageInterpreter:
    if settings.llm_provider == "disabled":
        return DisabledCustomerLanguageInterpreter()
    api_key = settings.openai_api_key
    model = settings.openai_model
    if api_key is None or model is None:  # Guarded by settings validation.
        raise ValueError("OpenAI language interpreter is not fully configured")
    return OpenAIResponsesLanguageInterpreter(
        api_key=api_key.get_secret_value(),
        model=model,
        timeout_seconds=settings.llm_timeout_seconds,
    )


def _rpc_error(
    request_id: str | int | None,
    code: int,
    message: str,
    data: object | None = None,
) -> JSONResponse:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "error": error})


app = create_app()
