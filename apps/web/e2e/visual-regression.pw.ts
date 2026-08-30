import { expect, test } from "@playwright/test";

import {
  FITBOX_CASE_PATH,
  assertNoHorizontalOverflow,
  captureEvidence,
  expectMockDashboard,
  prepareVisualPage,
} from "./support/fixtures";

test("public demo entry visual baseline", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "From failed invoice to an auditable next action.",
    }),
  ).toBeVisible();
  await prepareVisualPage(page);
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("public-demo-entry.png", {
    fullPage: true,
  });
  await captureEvidence(page, testInfo, "public-demo-entry.png");
});

test("Control Tower visual baseline", async ({ page }, testInfo) => {
  await page.goto("/dashboard");
  await expectMockDashboard(page);
  await prepareVisualPage(page);
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("control-tower.png", { fullPage: true });
  await captureEvidence(page, testInfo, "control-tower.png");
});

test("case workspace visual baseline", async ({ page }, testInfo) => {
  await page.goto(FITBOX_CASE_PATH);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Aarav Sharma · FitBox Annual",
    }),
  ).toBeVisible();
  await prepareVisualPage(page);
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("case-workspace.png", { fullPage: true });
  await captureEvidence(page, testInfo, "case-workspace.png");
});

test("product tour visual baseline", async ({ page }, testInfo) => {
  await page.goto("/dashboard");
  await expectMockDashboard(page);
  await prepareVisualPage(page);
  const trigger = page.getByRole("button", { name: /product tour/i });
  await expect(trigger).toContainText("1/5 pages");
  // This is a visual assertion; DOM activation avoids touch-emulation timing
  // around the animated fixed panel while preserving the actual click path.
  await trigger.evaluate((button: HTMLButtonElement) => button.click());
  await expect(
    page.getByRole("dialog", { name: "RecoveryOS product tour" }),
  ).toBeVisible();
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("fitbox-demo-guide.png", {
    fullPage: true,
  });
  await captureEvidence(page, testInfo, "fitbox-demo-guide.png");
});

test("voice safety visual baseline", async ({ page }, testInfo) => {
  await page.goto("/voice");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Rehearse every intent before a real call",
    }),
  ).toBeVisible();
  await prepareVisualPage(page);
  await assertNoHorizontalOverflow(page);
  await expect(page).toHaveScreenshot("voice-safety.png", { fullPage: true });
  await captureEvidence(page, testInfo, "voice-safety.png");
});
