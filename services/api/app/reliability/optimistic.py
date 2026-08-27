"""Compare-and-swap updates for versioned recovery cases."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from services.api.app.models import RecoveryCase


class OptimisticVersionConflict(RuntimeError):
    def __init__(self, *, case_id: str, expected_version: int) -> None:
        super().__init__(
            f"recovery case {case_id!r} no longer has expected version {expected_version}"
        )
        self.case_id = case_id
        self.expected_version = expected_version
        self.code = "RECOVERY_CASE_VERSION_CONFLICT"


_ALLOWED_FIELDS = frozenset(
    {
        "case_outcome",
        "payment_state",
        "subscription_state",
        "contact_disposition",
        "revenue_attribution",
        "arrears_collected_paise",
        "case_recovered",
        "subscription_reactivated",
        "recovered_at",
    }
)


async def compare_and_swap_case(
    session: AsyncSession,
    *,
    merchant_id: str,
    case_id: str,
    expected_version: int,
    changes: Mapping[str, Any],
) -> int:
    """Apply one atomic case transition, rejecting stale concurrent writers."""

    if expected_version < 1:
        raise ValueError("expected_version must be positive")
    unknown = set(changes) - _ALLOWED_FIELDS
    if unknown:
        raise ValueError(f"unsupported recovery-case fields: {', '.join(sorted(unknown))}")
    if not changes:
        raise ValueError("at least one change is required")
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(RecoveryCase)
            .where(
                RecoveryCase.id == case_id,
                RecoveryCase.merchant_id == merchant_id,
                RecoveryCase.version == expected_version,
            )
            .values(**dict(changes), version=expected_version + 1)
        ),
    )
    if result.rowcount != 1:
        raise OptimisticVersionConflict(case_id=case_id, expected_version=expected_version)
    return expected_version + 1
