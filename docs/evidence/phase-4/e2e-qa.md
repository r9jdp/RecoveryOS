# Phase 4 E2E and visual QA evidence

The Phase 4 browser suite is deterministic, uses only mock provider boundaries, and runs with no
Razorpay, Twilio, ElevenLabs, Temporal Cloud, or hosted-database credentials.

Validated on 2026-08-28: all 24 Playwright project checks passed in 22.9 seconds, and the focused
reset/reseed pytest passed. The six committed visual baselines were then rerun without snapshot
updates to prove stability.

## Coverage

- Five-minute judge journey: demo login, Control Tower, case evidence, mock approval, approval
  queue, and RecoveryBench.
- Safety: opt-out, already-paid reconciliation language, kill switch, voice intent precedence,
  guarded-call gate, exact-scope A2A approval, and replay rejection.
- Resilience: labelled loading UI, API fallback, voice 503 handling without automatic retry, and
  customer-agent retry.
- Accessibility: keyboard-only approval, focus trap and restoration, semantic labels, ARIA
  references, landmark/headings, duplicate IDs, positive tab order, and horizontal overflow.
- Visual regression: 1440x960 desktop and 390x844 mobile baselines for Control Tower, case
  workspace, and voice safety.
- Reset/reseed: fresh SQLite schema, Phase 3 nonce cleanup, unrelated-merchant preservation, and
  exactly-one FitBox case after repeated resets.

## Screenshot evidence

The six review-ready captures live in `apps/web/public/evidence/phase-4/`:

- `desktop-chromium-control-tower.png`
- `desktop-chromium-case-workspace.png`
- `desktop-chromium-voice-safety.png`
- `mobile-chromium-control-tower.png`
- `mobile-chromium-case-workspace.png`
- `mobile-chromium-voice-safety.png`

## Local commands

From the repository root:

```powershell
pnpm --filter @recovery-os/web exec playwright test --config e2e/playwright.config.ts
uv run pytest tests/e2e/test_reset_reseed.py
```

Create/update visual baselines and README-ready evidence only after intentional visual review:

```powershell
pnpm --filter @recovery-os/web exec playwright test --config e2e/playwright.config.ts `
  --grep "visual baseline" --update-snapshots
$env:RECOVERYOS_CAPTURE_EVIDENCE = "1"
pnpm --filter @recovery-os/web exec playwright test --config e2e/playwright.config.ts `
  --grep "visual baseline"
```

The shared `apps/web/package.json` remains coordinator-owned. Its existing `e2e` script should be
changed from `playwright test` to `playwright test --config e2e/playwright.config.ts` during
integration.

## Scanner scope

The native scan intentionally avoids an undeclared package dependency. It checks deterministic
structural and keyboard failures using browser APIs. The coordinator may add
`@axe-core/playwright` to the shared manifest/lockfile for a full axe ruleset; this suite remains a
fast complementary gate rather than claiming full WCAG conformance.
