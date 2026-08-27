"""Server-only customer-agent configuration."""

from __future__ import annotations

import hashlib
from typing import Literal

from pydantic import Field
from pydantic.types import SecretStr
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
    task_store: Literal["memory", "sql"] = "memory"
    database_url: SecretStr | None = None

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

    def durable_database_url(self) -> str:
        if self.task_store != "sql":
            raise ValueError("durable database URL requested while task store is not sql")
        if self.database_url is None:
            raise ValueError(
                "CUSTOMER_AGENT_DATABASE_URL is required when CUSTOMER_AGENT_TASK_STORE=sql"
            )
        return self.database_url.get_secret_value()
