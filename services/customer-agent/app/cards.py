"""Public A2A Agent Card for the customer authorization agent."""

from __future__ import annotations

RECOVERY_MANDATE_EXTENSION_URI = "https://recoveryos.dev/a2a/recovery-mandate/v1"
RECOVERY_RECEIPT_EXTENSION_URI = "https://recoveryos.dev/a2a/recovery-receipt/v1"


def customer_agent_card(
    *,
    origin: str,
    signer_key_id: str,
    public_key: str,
    accepted_receipt_signer_key_ids: list[str],
) -> dict[str, object]:
    return {
        "name": "RecoveryOS Customer Authorization Agent",
        "description": (
            "Presents an exact recovery surface for customer approval and returns a signed, "
            "single-use mandate. It never executes a payment."
        ),
        "supportedInterfaces": [
            {
                "url": f"{origin.rstrip('/')}/rpc",
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
                    "params": {
                        "signingAlgorithm": "Ed25519",
                        "signerKeyId": signer_key_id,
                        "publicKeyBase64Url": public_key,
                    },
                },
                {
                    "uri": RECOVERY_RECEIPT_EXTENSION_URI,
                    "required": True,
                    "params": {
                        "authentication": "Ed25519",
                        "protocolVersion": "recovery.receipt.v1",
                        "canonicalization": "RECOVERYOS_CANONICAL_JSON_V1",
                        "acceptedSignerKeyIds": accepted_receipt_signer_key_ids,
                        "scope": [
                            "receipt_id",
                            "task_id",
                            "mandate_id",
                            "merchant_id",
                            "case_id",
                            "exact_amount_paise",
                            "currency",
                            "provider_reference",
                            "payment_state",
                            "observed_at",
                        ],
                    },
                },
            ],
        },
        "defaultInputModes": ["application/json"],
        "defaultOutputModes": ["application/json"],
        "skills": [
            {
                "id": "authorize-exact-recovery-surface",
                "name": "Authorize an exact recovery surface",
                "description": "Collects explicit customer approval for a bounded payment surface.",
                "tags": ["recovery", "approval", "payment-safety"],
                "inputModes": ["application/json"],
                "outputModes": ["application/json"],
                "examples": ["Review and approve this exact subscription invoice surface."],
            }
        ],
        "securitySchemes": {},
        "security": [],
    }
