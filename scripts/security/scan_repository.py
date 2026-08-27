"""Scan tracked source and built browser assets for high-confidence secret exposure."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Razorpay live key", re.compile(rb"\brzp_live_[A-Za-z0-9]{12,}\b")),
    ("Stripe live secret", re.compile(rb"\bsk_live_[A-Za-z0-9]{16,}\b")),
    ("GitHub token", re.compile(rb"\b(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
)
SENSITIVE_ASSIGNMENT = re.compile(
    rb"(?im)^\s*(?:export\s+)?(?:RAZORPAY_KEY_SECRET|RAZORPAY_WEBHOOK_SECRET|"
    rb"TWILIO_AUTH_TOKEN|ELEVENLABS_API_KEY|ELEVENLABS_WEBHOOK_SECRET|"
    rb"CUSTOMER_AGENT_ED25519_PRIVATE_KEY|TEMPORAL_API_KEY)[ \t]*=[ \t]*"
    rb"([^\s#][^\r\n#]*)"
)
PLACEHOLDERS = {b'""', b"''", b"replace-me", b"changeme", b"example", b"<redacted>"}
FORBIDDEN_BROWSER_NAMES = (
    b"RAZORPAY_KEY_SECRET",
    b"RAZORPAY_WEBHOOK_SECRET",
    b"TWILIO_AUTH_TOKEN",
    b"ELEVENLABS_API_KEY",
    b"CUSTOMER_AGENT_ED25519_PRIVATE_KEY",
    b"TEMPORAL_API_KEY",
    b"DATABASE_URL",
)


def tracked_files(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def scan_file(path: Path, *, browser_asset: bool = False) -> list[str]:
    if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
        return []
    data = path.read_bytes()
    if b"\0" in data:
        return []
    findings = [name for name, pattern in SECRET_PATTERNS if pattern.search(data)]
    for match in SENSITIVE_ASSIGNMENT.finditer(data):
        value = match.group(1).strip().strip(b"\"'").lower()
        is_placeholder = (
            value in PLACEHOLDERS
            or (value.startswith(b"<") and value.endswith(b">"))
            or (value.startswith(b"${") and value.endswith(b"}"))
            or value.startswith((b"change-me", b"replace-me", b"example"))
        )
        if value and not is_placeholder:
            findings.append("non-empty sensitive environment assignment")
            break
    if browser_asset:
        findings.extend(
            f"server-only name {name.decode()} in browser asset"
            for name in FORBIDDEN_BROWSER_NAMES
            if name in data
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--browser-dir", type=Path)
    arguments = parser.parse_args()
    root = arguments.root.resolve()
    failures: list[str] = []
    for path in tracked_files(root):
        for finding in scan_file(path):
            failures.append(f"{path.relative_to(root)}: {finding}")

    browser_dir = arguments.browser_dir
    if browser_dir and browser_dir.exists():
        for path in browser_dir.rglob("*"):
            if path.is_file():
                for finding in scan_file(path, browser_asset=True):
                    failures.append(f"{path}: {finding}")

    if failures:
        print("Secret exposure scan failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Secret exposure scan passed for tracked source and supplied browser assets.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
