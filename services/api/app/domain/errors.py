"""Structured, transport-neutral error and pagination contracts."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]+$")
    message: str
    field: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: ErrorDetail
    request_id: str
    correlation_id: str


class PageMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_cursor: str | None = None
    has_more: bool
    limit: int = Field(ge=1, le=100)


class CursorPage[ItemT](BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ItemT]
    page: PageMeta
