"""Isolated RecoveryOS Agent Card router for coordinator registration."""

from __future__ import annotations

import os
import secrets
from datetime import UTC
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from services.api.app.integrations.a2a.client import (
    RECOVERY_MANDATE_EXTENSION_URI,
    A2ACustomerAgentClient,
    CustomerAgentProtocolError,
)
from services.api.app.providers.contracts import (
    CustomerAgentRecoveryRequest,
    CustomerAgentTask,
)

router = APIRouter(tags=["a2a"])


def _truthy(value: str | None) -> bool:
    return value is not None and value.casefold() in {"1", "true", "yes", "on"}


def get_customer_agent_client() -> A2ACustomerAgentClient:
    return A2ACustomerAgentClient(
        origin=os.getenv("CUSTOMER_AGENT_ORIGIN", "http://localhost:8010"),
        bearer_token=os.getenv("CUSTOMER_AGENT_S2S_BEARER_TOKEN", "").strip() or None,
    )


CustomerAgentDependency = Annotated[A2ACustomerAgentClient, Depends(get_customer_agent_client)]


def _rpc_error(request_id: str | int | None, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


def _task_result(task: CustomerAgentTask) -> dict[str, object]:
    state = f"TASK_STATE_{task.state}"
    artifacts: list[dict[str, object]] = []
    if task.artifact is not None:
        artifacts.append(
            {
                "artifactId": str(task.artifact.get("mandate_id", task.remote_task_id)),
                "name": "Customer authorization artifact",
                "parts": [{"data": task.artifact}],
            }
        )
    return {
        "id": task.remote_task_id,
        "status": {"state": state, "timestamp": task.updated_at.astimezone(UTC).isoformat()},
        "artifacts": artifacts,
        "metadata": {"delegatedBy": "RecoveryOS", "updatedAt": task.updated_at.isoformat()},
    }


@router.get("/.well-known/agent-card.json", include_in_schema=False)
async def recovery_agent_card() -> dict[str, object]:
    origin = os.getenv("RECOVERY_AGENT_ORIGIN", "http://localhost:8000").rstrip("/")
    bearer_auth_required = _inbound_bearer_token() is not None
    security_schemes: dict[str, object] = {}
    security: list[dict[str, list[str]]] = []
    if bearer_auth_required:
        security_schemes = {
            "a2aInboundBearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "opaque",
                "description": "Bearer credential for inbound A2A delegation.",
            }
        }
        security = [{"a2aInboundBearer": []}]
    return {
        "name": "RecoveryOS Recovery Agent",
        "description": (
            "Diagnoses failed subscription payments and requests bounded customer authorization. "
            "Payment execution remains in deterministic provider activities."
        ),
        "supportedInterfaces": [
            {
                "url": f"{origin}/a2a/rpc",
                "protocolBinding": "JSONRPC",
                "protocolVersion": "1.0",
            }
        ],
        "version": "0.1.0",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "extensions": [
                {
                    "uri": RECOVERY_MANDATE_EXTENSION_URI,
                    "required": True,
                }
            ],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "request-customer-recovery-authorization",
                "name": "Request recovery authorization",
                "description": "Creates an exact recovery.request.v2 DataPart for customer review.",
                "tags": ["recovery", "subscription", "authorization"],
                "inputModes": ["application/json"],
                "outputModes": ["application/json"],
            }
        ],
        "securitySchemes": security_schemes,
        "security": security,
    }


@router.post("/a2a/rpc", include_in_schema=False)
async def recovery_agent_rpc(
    http_request: Request,
    client: CustomerAgentDependency,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    a2a_version: Annotated[str | None, Header(alias="A2A-Version")] = None,
    a2a_extensions: Annotated[str | None, Header(alias="A2A-Extensions")] = None,
) -> JSONResponse:
    """Delegate bounded authorization tasks without executing a payment."""

    if not _bearer_authorized(authorization, _inbound_bearer_token()):
        return JSONResponse(
            {"detail": "A valid service credential is required"},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = await http_request.json()
    except ValueError:
        return _rpc_error(None, -32700, "Parse error")
    if not isinstance(payload, dict):
        return _rpc_error(None, -32600, "Invalid JSON-RPC request")
    request_id = payload.get("id")
    safe_request_id = request_id if isinstance(request_id, (str, int)) else None
    if a2a_version != "1.0":
        return _rpc_error(safe_request_id, -32008, "A2A protocol version is not supported")
    extensions = {value.strip() for value in (a2a_extensions or "").split(",") if value.strip()}
    if RECOVERY_MANDATE_EXTENSION_URI not in extensions:
        return _rpc_error(safe_request_id, -32009, "Recovery mandate extension support is required")
    if not _truthy(os.getenv("A2A_ENABLED")):
        return _rpc_error(safe_request_id, -32004, "A2A delegation is disabled")
    if payload.get("jsonrpc") != "2.0":
        return _rpc_error(safe_request_id, -32600, "Invalid JSON-RPC request")

    method = payload.get("method")
    params = payload.get("params")
    if not isinstance(params, dict):
        return _rpc_error(safe_request_id, -32602, "Invalid params")
    try:
        if method == "SendMessage":
            message = params.get("message")
            if not isinstance(message, dict):
                raise ValueError("SendMessage params.message is required")
            parts = message.get("parts")
            if not isinstance(parts, list) or not parts or not isinstance(parts[0], dict):
                raise ValueError("SendMessage requires a DataPart")
            data = parts[0].get("data")
            request = CustomerAgentRecoveryRequest.model_validate(data)
            task = await client.send_recovery_request(request)
            result: dict[str, object] = {"task": _task_result(task)}
        elif method == "GetTask":
            task_id = params.get("id")
            if not isinstance(task_id, str) or not task_id:
                raise ValueError("GetTask params.id is required")
            task = await client.get_task(remote_task_id=task_id)
            result = _task_result(task)
        elif method == "CancelTask":
            task_id = params.get("id")
            reason = params.get("reason")
            if not isinstance(task_id, str) or not task_id or not isinstance(reason, str):
                raise ValueError("CancelTask requires params.id and params.reason")
            task = await client.cancel_task(remote_task_id=task_id, reason=reason)
            result = _task_result(task)
        else:
            return _rpc_error(safe_request_id, -32601, "Method not found")
    except (ValidationError, ValueError) as exc:
        return _rpc_error(safe_request_id, -32602, str(exc))
    except (CustomerAgentProtocolError, httpx.HTTPError):
        return _rpc_error(safe_request_id, -32003, "Customer agent delegation failed")

    return JSONResponse({"jsonrpc": "2.0", "id": safe_request_id, "result": result})


def _inbound_bearer_token() -> str | None:
    return os.getenv("RECOVERY_AGENT_A2A_INBOUND_BEARER_TOKEN", "").strip() or None


def _bearer_authorized(authorization: str | None, expected_token: str | None) -> bool:
    if expected_token is None:
        return True
    scheme, separator, supplied_token = (authorization or "").partition(" ")
    if separator != " " or scheme.casefold() != "bearer":
        return False
    return secrets.compare_digest(supplied_token.encode(), expected_token.encode())
