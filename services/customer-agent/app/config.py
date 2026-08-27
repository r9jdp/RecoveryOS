"""Server-only customer-agent configuration."""

from __future__ import annotations

import hashlib

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_MOCK_SEED = hashlib.sha256(b"recoveryos-customer-agent-mock-key-v1").digest()


class CustomerAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CUSTOMER_AGENT_", extra="ignore")

    origin: str = "http://localhost:8010"
    web_origin: str = "http://localhost:3000"
    signer_key_id: str = "recoveryos-mock-2026-01"
    ed25519_private_key: str | None = None
    real_signing_enabled: bool = False
    request_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    def signing_seed(self) -> bytes:
        if self.real_signing_enabled:
            if not self.ed25519_private_key:
                raise ValueError(
                    "CUSTOMER_AGENT_ED25519_PRIVATE_KEY is required when real signing is enabled"
                )
            import base64

            value = self.ed25519_private_key
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
        return _MOCK_SEED
