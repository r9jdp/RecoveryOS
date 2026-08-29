from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).parents[2]


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_checked_in_migrations_are_expand_compatible() -> None:
    checker = _load("check_migrations", ROOT / "scripts" / "deployment" / "check_migrations.py")
    migration_dir = ROOT / "services" / "api" / "alembic" / "versions"
    findings = {
        path.name: checker.inspect_upgrade(path)
        for path in migration_dir.glob("*.py")
        if checker.inspect_upgrade(path)
    }
    assert findings == {}


def test_migration_checker_rejects_destructive_upgrade(tmp_path: Path) -> None:
    checker = _load(
        "check_migrations_destructive",
        ROOT / "scripts" / "deployment" / "check_migrations.py",
    )
    migration = tmp_path / "unsafe.py"
    migration.write_text(
        "from alembic import op\n\ndef upgrade():\n    op.drop_table('payments')\n",
        encoding="utf-8",
    )
    assert checker.inspect_upgrade(migration) == ["line 4: op.drop_table is not expand-compatible"]


def test_env_reader_does_not_execute_or_expand_values(tmp_path: Path) -> None:
    env_file_module = _load("env_file", ROOT / "scripts" / "deployment" / "env_file.py")
    path = tmp_path / "service.env"
    path.write_text(
        'PAYMENT_PROVIDER="mock"\nUNTRUSTED=$(touch should-not-exist)\n',
        encoding="utf-8",
    )
    values = env_file_module.read_env_file(path)
    assert values == {
        "PAYMENT_PROVIDER": "mock",
        "UNTRUSTED": "$(touch should-not-exist)",
    }
    assert not (tmp_path / "should-not-exist").exists()


def test_database_url_is_split_into_libpq_variables_without_logging() -> None:
    writer = _load("write_pg_env", ROOT / "scripts" / "deployment" / "write_pg_env.py")
    values = writer.libpq_values(
        "postgresql+psycopg://merchant:p%40ss@db.example.com:5433/recovery?sslmode=require"
    )
    assert values == {
        "PGHOST": "db.example.com",
        "PGPORT": "5433",
        "PGUSER": "merchant",
        "PGPASSWORD": "p@ss",
        "PGDATABASE": "recovery",
        "PGCONNECT_TIMEOUT": "10",
        "PGSSLMODE": "require",
    }


def test_public_demo_gate_is_fail_closed() -> None:
    demo_gate = _load(
        "validate_public_demo",
        ROOT / "scripts" / "deployment" / "validate_public_demo.py",
    )
    safe_api = {
        "PAYMENT_PROVIDER": "mock",
        "VOICE_PROVIDER": "mock",
        "VOICE_REAL_CALLS_ENABLED": "false",
        "A2A_ENABLED": "false",
        "RAZORPAY_TEST_MODE_REQUIRED": "true",
        "VOICE_DAILY_CALL_LIMIT": "10",
    }
    safe_agent = {"CUSTOMER_AGENT_REAL_SIGNING_ENABLED": "false"}
    assert demo_gate.validate(safe_api, safe_agent) == []

    unsafe_api = {**safe_api, "PAYMENT_PROVIDER": "razorpay", "RAZORPAY_KEY_SECRET": "secret"}
    failures = demo_gate.validate(unsafe_api, safe_agent)
    assert any("PAYMENT_PROVIDER" in failure for failure in failures)
    assert any("RAZORPAY_KEY_SECRET" in failure for failure in failures)


def test_secret_scanner_rejects_live_token_and_browser_server_name(tmp_path: Path) -> None:
    scanner = _load("scan_repository", ROOT / "scripts" / "security" / "scan_repository.py")
    source = tmp_path / "bad.env"
    fake_live_token = "rzp_" + "live_" + "1234567890123456"
    source.write_text(f"RAZORPAY_KEY_SECRET={fake_live_token}\n", encoding="utf-8")
    findings = scanner.scan_file(source)
    assert "Razorpay live key" in findings
    assert "non-empty sensitive environment assignment" in findings

    browser = tmp_path / "client.js"
    browser.write_text("const key = 'TWILIO_AUTH_TOKEN'", encoding="utf-8")
    assert "server-only name TWILIO_AUTH_TOKEN in browser asset" in scanner.scan_file(
        browser, browser_asset=True
    )


def test_shell_scripts_enable_strict_error_handling() -> None:
    scripts = [
        *sorted((ROOT / "deploy" / "scripts").glob("*.sh")),
        *sorted((ROOT / "scripts" / "security").glob("*.sh")),
    ]
    assert scripts
    for script in scripts:
        lines = script.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "#!/usr/bin/env bash", script
        assert lines[1] == "set -Eeuo pipefail", script


def test_agent_card_smoke_uses_supported_interface_and_exact_rpc_origin() -> None:
    smoke = (ROOT / "deploy" / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    assert 'payload.get("supportedInterfaces", [])' in smoke
    assert "f\"{expected_agent_origin.rstrip('/')}/rpc\"" in smoke
    assert 'interface.get("protocolBinding") == "JSONRPC"' in smoke
    assert 'payload.get("url"' not in smoke


def test_hosted_customer_agent_checks_sql_readiness_before_promotion() -> None:
    smoke = (ROOT / "deploy" / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    monitor = (ROOT / "deploy" / "scripts" / "monitor.sh").read_text(encoding="utf-8")

    assert 'retry_json "${agent_base_url}/health/ready" agent-ready' in smoke
    assert 'payload.get("store") == "sql"' in smoke
    assert 'probe_agent_ready agent-ready "${agent_base_url}/health/ready"' in monitor
    assert 'payload.get("store") == "sql"' in monitor
