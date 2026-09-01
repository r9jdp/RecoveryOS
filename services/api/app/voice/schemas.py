"""API contracts private to the Phase 3 voice module."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VoiceApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartVoiceContactRequest(VoiceApiModel):
    case_id: str
    idempotency_key: str = Field(min_length=8, max_length=200)
    max_duration_seconds: int = Field(default=180, gt=0, le=180)


class StartVoiceContactResponse(VoiceApiModel):
    attempt_id: str
    provider: str
    status: Literal["SUBMITTED", "REJECTED", "UNCERTAIN"]
    reason_code: str
    provider_call_id: str | None = None
    retry_permitted: Literal[False] = False


class VoiceAttemptResponse(VoiceApiModel):
    id: str
    case_id: str
    status: str
    disposition: str | None
    transcript: str | None
    detected_intent: str | None
    confidence_basis_points: int | None = Field(default=None, ge=0, le=10_000)
    duration_seconds: int | None = Field(default=None, ge=0, le=180)
    disclosure_delivered_at: datetime | None
    created_at: datetime


class VoiceTimelineResponse(VoiceApiModel):
    items: list[VoiceAttemptResponse]


class VoiceContactSetupRequest(VoiceApiModel):
    destination_token: str = Field(pattern=r"^\+[1-9]\d{7,14}$", max_length=16)
    preferred_language: str = Field(
        min_length=2,
        max_length=32,
        pattern=r"^[A-Za-z]{2,3}(-[A-Za-z]{2})?$",
    )
    consent_granted: bool


class VoiceEligibilityResponse(VoiceApiModel):
    case_id: str
    customer_id: str | None
    eligible: bool
    reason_code: str
    destination_configured: bool
    destination_allowlisted: bool
    consent_verified_at: datetime | None
    opted_out_at: datetime | None
    preferred_language: str | None


class BrowserTranscriptRequest(VoiceApiModel):
    transcript: str = Field(min_length=1, max_length=10_000)
    confidence_basis_points: int = Field(default=10_000, ge=0, le=10_000)


class BrowserTranscriptResponse(VoiceApiModel):
    detected_intent: str
    disposition: str
    contact_must_end: bool
    suppression_persisted: bool


class LiveVoiceIntentRequest(VoiceApiModel):
    attempt_id: str = Field(min_length=8, max_length=200)
    event_id: str | None = Field(default=None, min_length=1, max_length=200)
    intent: str = Field(min_length=1, max_length=64)
    confidence_basis_points: int | None = Field(default=None, ge=0, le=10_000)


class LiveVoiceIntentResponse(VoiceApiModel):
    accepted: Literal[True] = True
    duplicate: bool
    detected_intent: str
    contact_must_end: bool
    suppression_persisted: bool


class WebhookAcceptedResponse(VoiceApiModel):
    accepted: Literal[True] = True
    duplicate: bool
