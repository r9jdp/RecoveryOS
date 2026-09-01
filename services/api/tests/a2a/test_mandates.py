from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from services.api.app.integrations.a2a.mandates import (
    MandateVerificationError,
    MandateVerifier,
)
from services.api.app.integrations.a2a.models import (
    ExpectedMandateScope,
    RecoveryMandateData,
)
from services.api.app.integrations.a2a.nonce_store import InMemoryNonceStore


def signed_mandate(  # type: ignore[no-untyped-def]
    *, expires_at: datetime | None = None, **changes: object
):
    from app.models import RecoveryMandateData as SignerMandateData
    from app.signing import MandateSigner

    now = datetime(2026, 8, 28, 10, 0, tzinfo=UTC)
    signer = MandateSigner.from_seed(signer_key_id="customer-key-1", seed=bytes(range(32)))
    values: dict[str, object] = {
        "mandate_id": "mandate-1",
        "nonce": "nonce-1",
        "signer_key_id": "customer-key-1",
        "task_id": "task-1",
        "merchant_id": "merchant-1",
        "case_id": "case-1",
        "customer_id": "customer-1",
        "recovery_action_id": "action-1",
        "failed_invoice_id": "invoice-local-1",
        "exact_amount_paise": 149900,
        "currency": "INR",
        "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
        "payment_surface_reference": "inv_123",
        "issued_at": now,
        "expires_at": expires_at or now + timedelta(minutes=10),
    }
    values.update(changes)
    data = SignerMandateData.model_validate(values)
    return signer, signer.sign(data).model_dump(mode="json"), now


def expected_scope(**changes: object) -> ExpectedMandateScope:
    values: dict[str, object] = {
        "task_id": "task-1",
        "merchant_id": "merchant-1",
        "case_id": "case-1",
        "customer_id": "customer-1",
        "recovery_action_id": "action-1",
        "failed_invoice_id": "invoice-local-1",
        "exact_amount_paise": 149900,
        "currency": "INR",
        "payment_surface_type": "SUBSCRIPTION_INVOICE_LINK",
        "payment_surface_reference": "inv_123",
    }
    values.update(changes)
    return ExpectedMandateScope.model_validate(values)


def verifier(signer, store: InMemoryNonceStore | None = None) -> MandateVerifier:  # type: ignore[no-untyped-def]
    return MandateVerifier(
        pinned_public_keys={signer.signer_key_id: signer.public_key_base64},
        nonce_store=store or InMemoryNonceStore(),
    )


@pytest.mark.asyncio
async def test_identical_verifier_retry_recovers_the_same_claim() -> None:
    signer, envelope, now = signed_mandate()
    active = verifier(signer)
    first = await active.verify_and_consume(envelope, expected=expected_scope(), now=now)
    retry = await active.verify_and_consume(
        envelope,
        expected=expected_scope(),
        now=now + timedelta(seconds=1),
    )
    assert first.data == RecoveryMandateData.model_validate(envelope["data"])
    assert retry.data == first.data
    assert retry.claim_id == first.claim_id


@pytest.mark.asyncio
async def test_identical_retry_after_expiry_recovers_only_a_previously_claimed_mandate() -> None:
    signer, envelope, now = signed_mandate()
    active = verifier(signer)

    first = await active.verify_and_consume(envelope, expected=expected_scope(), now=now)
    retry = await active.verify_and_consume(
        envelope,
        expected=expected_scope(),
        now=now + timedelta(minutes=11),
    )

    assert retry.claim_id == first.claim_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "expected_changes"),
    [
        ({"exact_amount_paise": 149_901}, {"exact_amount_paise": 149_901}),
        ({"nonce": "nonce-2"}, {}),
    ],
)
async def test_changed_claim_cannot_reuse_nonce_or_mandate_id(
    changes: dict[str, object], expected_changes: dict[str, object]
) -> None:
    signer, envelope, now = signed_mandate()
    active = verifier(signer)
    await active.verify_and_consume(envelope, expected=expected_scope(), now=now)

    _, conflicting, _ = signed_mandate(**changes)
    with pytest.raises(MandateVerificationError) as replay:
        await active.verify_and_consume(
            conflicting,
            expected=expected_scope(**expected_changes),
            now=now,
        )
    assert replay.value.code == "REPLAYED"


@pytest.mark.asyncio
async def test_tampering_is_rejected_before_scope_evaluation() -> None:
    signer, envelope, now = signed_mandate()
    envelope["data"]["exact_amount_paise"] = 999900
    with pytest.raises(MandateVerificationError) as rejected:
        await verifier(signer).verify_and_consume(
            envelope,
            expected=expected_scope(exact_amount_paise=999900),
            now=now,
        )
    assert rejected.value.code == "INVALID_SIGNATURE"


@pytest.mark.asyncio
async def test_malformed_envelope_and_signature_encoding_have_structured_errors() -> None:
    signer, envelope, now = signed_mandate()
    with pytest.raises(MandateVerificationError) as malformed:
        await verifier(signer).verify_and_consume(
            {"algorithm": "Ed25519"},
            expected=expected_scope(),
            now=now,
        )
    assert malformed.value.code == "MALFORMED_MANDATE"

    envelope["signature"] = "not+base64url!"
    with pytest.raises(MandateVerificationError) as invalid_encoding:
        await verifier(signer).verify_and_consume(
            envelope,
            expected=expected_scope(),
            now=now,
        )
    assert invalid_encoding.value.code == "INVALID_ENCODING"


@pytest.mark.asyncio
async def test_legacy_v1_mandate_is_not_provider_executable() -> None:
    signer, envelope, now = signed_mandate()
    legacy = {
        **envelope,
        "data": {**envelope["data"], "protocol_version": "recovery.mandate.v1"},
    }
    with pytest.raises(MandateVerificationError) as rejected:
        await verifier(signer).verify_and_consume(
            legacy,
            expected=expected_scope(),
            now=now,
        )
    assert rejected.value.code == "MALFORMED_MANDATE"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changed", "value"),
    [
        ("merchant_id", "merchant-wrong"),
        ("case_id", "case-wrong"),
        ("recovery_action_id", "action-wrong"),
        ("failed_invoice_id", "invoice-local-wrong"),
        ("exact_amount_paise", 149901),
        ("payment_surface_reference", "inv_wrong"),
    ],
)
async def test_scope_confusion_is_rejected(changed: str, value: object) -> None:
    signer, envelope, now = signed_mandate()
    with pytest.raises(MandateVerificationError) as rejected:
        await verifier(signer).verify_and_consume(
            envelope,
            expected=expected_scope(**{changed: value}),
            now=now,
        )
    assert rejected.value.code == "SCOPE_MISMATCH"
    assert changed in str(rejected.value)


@pytest.mark.asyncio
async def test_expired_and_unknown_signer_mandates_are_rejected() -> None:
    signer, envelope, issued_at = signed_mandate()
    with pytest.raises(MandateVerificationError) as expired:
        await verifier(signer).verify_and_consume(
            envelope,
            expected=expected_scope(),
            now=issued_at + timedelta(minutes=11),
        )
    assert expired.value.code == "EXPIRED"

    wrong_signer, _, _ = signed_mandate()
    unknown = MandateVerifier(
        pinned_public_keys={"different-key": wrong_signer.public_key_base64},
        nonce_store=InMemoryNonceStore(),
    )
    with pytest.raises(MandateVerificationError) as rejected:
        await unknown.verify_and_consume(envelope, expected=expected_scope(), now=issued_at)
    assert rejected.value.code == "UNKNOWN_SIGNER_KEY"


@pytest.mark.asyncio
async def test_concurrent_identical_verification_is_idempotent() -> None:
    signer, envelope, now = signed_mandate()
    active = verifier(signer, InMemoryNonceStore())

    async def consume() -> str:
        try:
            await active.verify_and_consume(envelope, expected=expected_scope(), now=now)
        except MandateVerificationError as exc:
            return exc.code
        return "VERIFIED"

    results = await asyncio.gather(*(consume() for _ in range(25)))
    assert results == ["VERIFIED"] * 25
