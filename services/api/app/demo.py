"""Read-only Phase 0 fixture endpoints used before persistence is connected."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException

from services.api.app.runtime_mode import require_demo_mode

router = APIRouter(prefix="/v1/demo", tags=["demo"])
FixtureName = Literal["dashboard", "case-detail", "customer-agent", "customer-voice", "ml-lab"]
FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "fixtures"


@router.get(
    "/fixtures/{fixture_name}",
    operation_id="getDemoFixture",
    dependencies=[Depends(require_demo_mode)],
)
async def get_demo_fixture(fixture_name: FixtureName) -> dict[str, Any]:
    """Return a versioned, synthetic screen fixture with no provider side effects."""

    fixture_path = FIXTURE_ROOT / f"{fixture_name}.json"
    if not fixture_path.is_file():
        raise HTTPException(
            status_code=404,
            detail={"code": "FIXTURE_NOT_FOUND", "message": "The demo fixture does not exist."},
        )
    return cast(dict[str, Any], json.loads(fixture_path.read_text(encoding="utf-8")))
