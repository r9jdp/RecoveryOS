import { expect, test } from "@playwright/test";

import {
  assertNoHorizontalOverflow,
  scanSemanticAccessibility,
} from "./support/fixtures";

test("failure lab runs a simulated contract with keyboard and responsive safety evidence", async ({
  page,
}, testInfo) => {
  let submitted: Record<string, unknown> | null = null;
  await page.route(
    "**/__e2e-api/v1/simulations/failure-injection",
    async (route) => {
      submitted = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          scenario: "OUT_OF_ORDER_WEBHOOK",
          seed: 42,
          case_id: "case_e2e_failure_lab",
          payment_id: "pay_e2e_failure_lab",
          amount_paise: 149900,
          expected_final_payment_state: "CAPTURED",
          expected_revenue_entries: 1,
          deliveries: [
            {
              delivery_id: "delivery_capture",
              provider_event_id: "evt_capture",
              event_type: "payment.captured",
              occurred_at: "2026-08-27T09:45:00Z",
              delivered_at: "2026-08-27T09:45:03Z",
              observed_payment_state: "CAPTURED",
              authoritative_payment_state: "CAPTURED",
              evidence_kind: "SIMULATED",
              payload: {},
            },
            {
              delivery_id: "delivery_stale_failure",
              provider_event_id: "evt_stale_failure",
              event_type: "payment.failed",
              occurred_at: "2026-08-27T09:00:00Z",
              delivered_at: "2026-08-27T09:45:05Z",
              observed_payment_state: "FAILED",
              authoritative_payment_state: "CAPTURED",
              evidence_kind: "SIMULATED",
              payload: {},
            },
          ],
        }),
      });
    },
  );

  await page.goto("/failure-lab");
  await expect(
    page.getByRole("heading", { level: 1, name: "Failure Injection Lab" }),
  ).toBeVisible();
  await expect(
    page.getByText(/RAZORPAY TEST VERIFIED evidence is unavailable/),
  ).toBeVisible();

  const duplicate = page.getByRole("radio", { name: /Duplicate webhook/i });
  await duplicate.focus();
  await page.keyboard.press("ArrowRight");
  await expect(
    page.getByRole("radio", { name: /Out-of-order webhook/i }),
  ).toBeChecked();
  await page.getByLabel(/Deterministic seed/).fill("42");
  const run = page.getByRole("button", {
    name: "Run out-of-order webhook simulation",
  });
  await run.focus();
  await page.keyboard.press("Enter");

  await expect(
    page.getByRole("heading", { name: "Expected convergence" }),
  ).toBeVisible();
  await expect(page.getByText("Provider fetch wins")).toBeVisible();
  await expect(page.getByText("evt_stale_failure")).toBeVisible();
  expect(submitted).toEqual({
    scenario: "OUT_OF_ORDER_WEBHOOK",
    seed: 42,
    amount_paise: 149900,
    evidence_kind: "SIMULATED",
  });

  expect(await scanSemanticAccessibility(page)).toEqual([]);
  await assertNoHorizontalOverflow(page);

  if (process.env.RECOVERYOS_CAPTURE_EVIDENCE === "1") {
    await page.evaluate(() => {
      (document.activeElement as HTMLElement | null)?.blur();
      window.scrollTo({ top: 0, behavior: "instant" });
    });
    await page.screenshot({
      animations: "disabled",
      fullPage: true,
      path: `../../docs/assets/screenshots/${testInfo.project.name}-failure-lab.png`,
    });
  }
});
