"""Fail closed when a public demo environment can reach real providers."""

from __future__ import annotations

import argparse
from pathlib import Path

from env_file import read_env_file


def _normalized(values: dict[str, str], key: str, default: str = "") -> str:
    return values.get(key, default).strip().casefold()


def validate(api: dict[str, str], customer_agent: dict[str, str]) -> list[str]:
    failures: list[str] = []
    required_api = {
        "PAYMENT_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "VOICE_REAL_CALLS_ENABLED": "false",
        "A2A_ENABLED": "false",
        "RAZORPAY_TEST_MODE_REQUIRED": "true",
    }
    for key, expected in required_api.items():
        actual = _normalized(api, key)
        if actual != expected:
            failures.append(f"api.env {key} must be {expected!r}, found {actual!r}")
    if _normalized(customer_agent, "CUSTOMER_AGENT_REAL_SIGNING_ENABLED") != "false":
        failures.append("customer-agent.env CUSTOMER_AGENT_REAL_SIGNING_ENABLED must be 'false'")

    for key in (
        "RAZORPAY_KEY_SECRET",
        "RAZORPAY_WEBHOOK_SECRET",
        "TWILIO_AUTH_TOKEN",
        "ELEVENLABS_API_KEY",
        "ELEVENLABS_WEBHOOK_SECRET",
    ):
        if api.get(key, "").strip():
            failures.append(f"api.env {key} must be empty in the public mock demo")
    if customer_agent.get("CUSTOMER_AGENT_ED25519_PRIVATE_KEY", "").strip():
        failures.append(
            "customer-agent.env CUSTOMER_AGENT_ED25519_PRIVATE_KEY must be empty "
            "in the public mock demo"
        )

    limit = api.get("VOICE_DAILY_CALL_LIMIT", "10").strip()
    try:
        if int(limit) > 10:
            failures.append("api.env VOICE_DAILY_CALL_LIMIT must not exceed 10")
    except ValueError:
        failures.append("api.env VOICE_DAILY_CALL_LIMIT must be an integer")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("api_env", type=Path)
    parser.add_argument("customer_agent_env", type=Path)
    arguments = parser.parse_args()
    failures = validate(
        read_env_file(arguments.api_env), read_env_file(arguments.customer_agent_env)
    )
    if failures:
        print("Public demo safety gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Public demo safety gate passed: all real provider paths are disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
