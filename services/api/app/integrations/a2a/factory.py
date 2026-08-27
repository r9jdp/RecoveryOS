"""Server-only A2A factories for activities and provider boundaries."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from services.api.app.db.session import get_session_factory

from .mandates import MandateVerifier
from .nonce_store import SqlAlchemyNonceStore


class A2AConfigurationError(RuntimeError):
    pass


def load_pinned_public_keys(raw: str | None = None) -> Mapping[str, str]:
    encoded = raw if raw is not None else os.getenv("CUSTOMER_AGENT_PUBLIC_KEYS_JSON", "{}")
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise A2AConfigurationError("CUSTOMER_AGENT_PUBLIC_KEYS_JSON must be valid JSON") from exc
    if not isinstance(value, dict) or not value:
        raise A2AConfigurationError("at least one pinned customer-agent public key is required")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in value.items()):
        raise A2AConfigurationError("customer-agent public keys must map string IDs to strings")
    return {str(key): str(item) for key, item in value.items()}


def create_mandate_verifier_from_env(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> MandateVerifier:
    """Build the verifier used inside a non-deterministic Temporal activity."""

    return MandateVerifier(
        pinned_public_keys=load_pinned_public_keys(),
        nonce_store=SqlAlchemyNonceStore(session_factory or get_session_factory()),
    )
