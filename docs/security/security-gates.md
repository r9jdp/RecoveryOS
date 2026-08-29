# Secret and dependency security gates

Run the offline/high-confidence gate during ordinary development:

```bash
python3 scripts/security/scan_repository.py --browser-dir apps/web/.next/static
bash scripts/security/security-gate.sh --dry-run
```

The repository scanner examines tracked source for private keys and known live-token forms, rejects
non-placeholder assignments to server secret variables, and rejects server-only variable names in
built browser assets. It complements rather than replaces Gitleaks.

The release runner must install Gitleaks and pip-audit from pinned, checksum-verified releases, then
run:

```bash
bash scripts/security/security-gate.sh
```

The dependency gate verifies the frozen uv lock, exports hash-pinned production Python requirements,
runs pip-audit without package installation, and runs pnpm's production audit. Store redacted reports
as short-lived CI artifacts; never upload environment content that contains credentials.

Failures require dependency remediation or a time-bounded, owner-approved exception documented
outside source code. Do not add broad Gitleaks allowlists to make a release pass.

## CI wiring status

Pull-request CI runs the repository, migration, dependency, and Gitleaks history gates with no deploy
or provider secrets. Scanner versions are pinned in workflow definitions. A scheduled dependency
advisory rescan is not configured; the existing scheduled workflow probes public uptime only, so
advisory monitoring remains an operational follow-up.
