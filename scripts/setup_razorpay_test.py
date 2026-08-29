"""Create or reuse the RecoveryOS Razorpay Test plan and subscription.

The command is intentionally idempotent: it identifies its own test objects by
notes before creating anything. Credentials are read only from the process
environment and are never printed.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import httpx


API_ORIGIN = "https://api.razorpay.com"
FIXTURE_KEY = "recoveryos-fitbox-v1"
PLAN_NAME = "RecoveryOS FitBox Pro Monthly"


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def as_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items", [])
    return [item for item in items if isinstance(item, dict)]


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = await client.request(method, path, params=params, json=json_body)
    if response.is_error:
        try:
            message = response.json().get("error", {}).get("description")
        except (ValueError, AttributeError):
            message = None
        raise RuntimeError(
            f"Razorpay {method} {path} failed ({response.status_code}): "
            f"{message or 'unknown API error'}"
        )
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Razorpay {method} {path} returned an invalid response")
    return payload


async def main() -> None:
    key_id = required_env("RAZORPAY_KEY_ID")
    key_secret = required_env("RAZORPAY_KEY_SECRET")
    if not key_id.startswith("rzp_test_"):
        raise RuntimeError("Only a Razorpay Test key is allowed by this setup command")

    async with httpx.AsyncClient(
        base_url=API_ORIGIN,
        auth=(key_id, key_secret),
        timeout=30,
    ) as client:
        plans = as_items(
            await request(client, "GET", "/v1/plans", params={"count": 100})
        )
        plan = next(
            (
                item
                for item in plans
                if item.get("notes", {}).get("recoveryos_fixture") == FIXTURE_KEY
                and item.get("item", {}).get("name") == PLAN_NAME
            ),
            None,
        )
        plan_created = plan is None
        if plan is None:
            plan = await request(
                client,
                "POST",
                "/v1/plans",
                json_body={
                    "period": "monthly",
                    "interval": 1,
                    "item": {
                        "name": PLAN_NAME,
                        "amount": 149_900,
                        "currency": "INR",
                        "description": "FitBox Pro monthly test subscription",
                    },
                    "notes": {"recoveryos_fixture": FIXTURE_KEY},
                },
            )

        plan_id = str(plan["id"])
        subscriptions = as_items(
            await request(
                client,
                "GET",
                "/v1/subscriptions",
                params={"plan_id": plan_id, "count": 100},
            )
        )
        subscription = next(
            (
                item
                for item in subscriptions
                if item.get("notes", {}).get("recoveryos_fixture") == FIXTURE_KEY
                and item.get("status") not in {"cancelled", "completed", "expired"}
            ),
            None,
        )
        subscription_created = subscription is None
        if subscription is None:
            subscription = await request(
                client,
                "POST",
                "/v1/subscriptions",
                json_body={
                    "plan_id": plan_id,
                    "total_count": 12,
                    "quantity": 1,
                    "customer_notify": False,
                    "notes": {
                        "recoveryos_fixture": FIXTURE_KEY,
                        "merchant": "FitBox",
                    },
                },
            )

    print(
        json.dumps(
            {
                "mode": "razorpay_test",
                "plan": {
                    "id": plan_id,
                    "created": plan_created,
                    "amount_paise": 149_900,
                    "period": "monthly",
                },
                "subscription": {
                    "id": subscription.get("id"),
                    "created": subscription_created,
                    "status": subscription.get("status"),
                    "short_url": subscription.get("short_url"),
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
