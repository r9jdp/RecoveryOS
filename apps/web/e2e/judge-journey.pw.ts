import { expect, test } from "@playwright/test";

import {
  FITBOX_CASE_PATH,
  assertNoHorizontalOverflow,
  expectMockDashboard,
  mockMerchantMutations,
} from "./support/fixtures";

test("five-minute judge journey stays simulated and auditable", async ({
  page,
}) => {
  await mockMerchantMutations(page);
  await page.goto("/login");
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Recover the payment. Preserve the trust.",
    }),
  ).toBeVisible();
  await expect(
    page.getByText("No real provider action is enabled."),
  ).toBeVisible();

  await page.getByRole("button", { name: "Enter Control Tower" }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expectMockDashboard(page);
  await expect(page.getByText("₹1,499").first()).toBeVisible();
  await expect(
    page.getByText("Authoritative provider events only"),
  ).toBeVisible();

  await page.getByPlaceholder("Customer, case, plan, diagnosis").fill("Aarav");
  await page.getByRole("link", { name: "REC-FITBOX-AUG-2026" }).click();
  await expect(page).toHaveURL(new RegExp(`${FITBOX_CASE_PATH}$`));
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Aarav Sharma · FitBox Annual",
    }),
  ).toBeVisible();
  await expect(page.getByText("SIMULATED evidence")).toBeVisible();
  await expect(
    page.getByText("Standalone collection is blocked"),
  ).toBeVisible();

  await page.getByRole("button", { name: "Approve recovery" }).click();
  await expect(
    page.getByRole("status").filter({ hasText: "Approve accepted" }).first(),
  ).toBeVisible();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "No external action was taken." })
      .first(),
  ).toBeVisible();

  await page.getByRole("link", { name: "Approval queue" }).click();
  const review = page.getByRole("button", { name: "Review" });
  const dialog = page.getByRole("alertdialog", {
    name: "Approve this recovery surface?",
  });
  await expect(async () => {
    await review.click();
    await expect(dialog).toBeVisible({ timeout: 1_000 });
  }).toPass();
  await expect(dialog).toContainText("browser callback never proves payment");
  await dialog.getByRole("button", { name: "Approve exact surface" }).click();
  await expect(page.getByText("Approval queue is clear")).toBeVisible();

  await page.getByRole("link", { name: "Recovery Lab" }).click();
  await expect(
    page.getByRole("heading", { level: 1, name: "RecoveryBench" }),
  ).toBeVisible();
  await expect(
    page.getByText("simulated incremental recovery", { exact: false }).first(),
  ).toBeVisible();
  await expect(page.getByText("1,200").first()).toBeVisible();

  await assertNoHorizontalOverflow(page);
});

test("dashboard filters recover cleanly from an empty result", async ({
  page,
}) => {
  await page.goto("/dashboard");
  await expectMockDashboard(page);

  await page
    .getByPlaceholder("Customer, case, plan, diagnosis")
    .fill("missing case");
  await expect(page.getByText("No matching cases")).toBeVisible();
  await page.getByRole("button", { name: "Clear filter" }).click();
  await expect(
    page.getByRole("link", { name: "REC-FITBOX-AUG-2026" }),
  ).toBeVisible();
});
