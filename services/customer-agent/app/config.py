"""Server-only customer-agent configuration."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator
from pydantic.types import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from .signing import MandateSigner

_MOCK_SEED = hashlib.sha256(b"recoveryos-customer-agent-mock-key-v1").digest()
_MOCK_RECEIPT_SEED = hashlib.sha256(b"recoveryos-recovery-agent-receipt-mock-key-v1").digest()
_MOCK_RECEIPT_SIGNER_KEY_ID = "recoveryos-receipt-mock-2026-01"


class CustomerAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CUSTOMER_AGENT_",
        extra="ignore",
        populate_by_name=True,
    )

    origin: str = "http://localhost:8010"
    web_origin: str = "http://localhost:3000"
    signer_key_id: str = "recoveryos-mock-2026-01"
    ed25519_private_key: str | None = None
    real_signing_enabled: bool = False
    request_ttl_seconds: int = Field(default=900, ge=60, le=3600)
    task_store: Literal["memory", "sql"] = "memory"
    database_url: SecretStr | None = None
    receipt_verification_mode: Literal["mock", "pinned"] = "mock"
    recovery_agent_public_keys_json: SecretStr | None = None
    llm_provider: Literal["disabled", "openai"] = Field(
        default="disabled",
        validation_alias="LLM_PROVIDER",
    )
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
    )
    openai_model: str | None = Field(
        default=None,
        validation_alias="OPENAI_MODEL",
    )
    llm_timeout_seconds: float = Field(default=8.0, ge=1.0, le=30.0)

    @model_validator(mode="after")
    def require_openai_configuration(self) -> CustomerAgentSettings:
        if self.llm_provider != "openai":
            return self
        if self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip():
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if self.openai_model is None or not self.openai_model.strip():
            raise ValueError("OPENAI_MODEL is required when LLM_PROVIDER=openai")
        return self

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

    def recovery_receipt_public_keys(self) -> dict[str, str]:
        if self.receipt_verification_mode == "mock":
            mock_signer = MandateSigner.from_seed(
                signer_key_id=_MOCK_RECEIPT_SIGNER_KEY_ID,
                seed=_MOCK_RECEIPT_SEED,
            )
            return {_MOCK_RECEIPT_SIGNER_KEY_ID: mock_signer.public_key_base64}
        if self.recovery_agent_public_keys_json is None:
            raise ValueError(
                "CUSTOMER_AGENT_RECOVERY_AGENT_PUBLIC_KEYS_JSON is required in pinned mode"
            )
        try:
            parsed = json.loads(self.recovery_agent_public_keys_json.get_secret_value())
        except json.JSONDecodeError as exc:
            raise ValueError(
                "CUSTOMER_AGENT_RECOVERY_AGENT_PUBLIC_KEYS_JSON must be valid JSON"
            ) from exc
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("at least one recovery-agent receipt public key must be pinned")
        if not all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
        ):
            raise ValueError("recovery-agent receipt keys must map string IDs to strings")
        return parsed
