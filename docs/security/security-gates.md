# Secret, dependency, and container security gates

Run the offline/high-confidence gate during ordinary development:

```bash
python3 scripts/security/scan_repository.py --browser-dir apps/web/.next/static
bash scripts/security/security-gate.sh --dry-run
```

The repository scanner examines tracked source for private keys and known live-token forms, rejects
non-placeholder assignments to server secret variables, and rejects server-only variable names in
built browser assets. It complements rather than replaces Gitleaks.

The release runner must install Gitleaks, pip-audit, and Trivy from pinned, checksum-verified releases,
then run:

```bash
bash scripts/security/security-gate.sh
bash scripts/security/scan-images.sh OWNER recoveryos sha-COMMIT
```

The dependency gate verifies the frozen uv lock, exports hash-pinned production Python requirements,
runs pip-audit without package installation, and runs pnpm's production audit. The image gate rejects
unfixed high/critical vulnerabilities and secrets in all three service images. Store redacted reports
as short-lived CI artifacts; never upload SBOM/environment content that contains private registry
credentials.

Failures require dependency/image remediation or a time-bounded, owner-approved exception documented
outside source code. Do not add broad Gitleaks allowlists or Trivy ignore files to make a release pass.

## Coordinator-owned CI wiring request

The coordinator should add the repository scan to pull-request CI and place dependency/image scans
between tests/build and deployment. Pin scanner versions in the workflow, grant read-only repository
access, and keep the security job free of deploy/provider secrets. A scheduled weekly run catches newly
published advisories even when the lockfiles have not changed.
