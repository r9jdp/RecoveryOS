"""A2A customer-agent client and signed-mandate verification boundary."""

from .client import A2ACustomerAgentClient
from .factory import A2AConfigurationError, create_mandate_verifier_from_env
from .mandates import MandateVerifier, VerifiedMandate
from .models import ExpectedMandateScope
from .nonce_store import InMemoryNonceStore, SqlAlchemyNonceStore
from .receipts import (
    RecoveryReceiptData,
    RecoveryReceiptSigner,
    SignedRecoveryReceipt,
    create_receipt_signer_from_env,
)

__all__ = [
    "A2ACustomerAgentClient",
    "A2AConfigurationError",
    "ExpectedMandateScope",
    "InMemoryNonceStore",
    "MandateVerifier",
    "RecoveryReceiptData",
    "RecoveryReceiptSigner",
    "SignedRecoveryReceipt",
    "SqlAlchemyNonceStore",
    "VerifiedMandate",
    "create_mandate_verifier_from_env",
    "create_receipt_signer_from_env",
]
