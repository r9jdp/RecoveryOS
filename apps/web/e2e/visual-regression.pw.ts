import { expect, test } from "@playwright/test";

import {
  FITBOX_CASE_PATH,
  assertNoHorizontalOverflow,
  captureEvidence,
  expectMockDashboard,
  prepareVisualPage,
} from "./support/fixtures";

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
