import { expect, test } from "@playwright/test";

import {
  FITBOX_CASE_PATH,
  assertNoHorizontalOverflow,
  expectMockDashboard,
  mockMerchantMutations,
  scanSemanticAccessibility,
  tabTo,
} from "./support/fixtures";

const merchantRoutes = [
  ["/dashboard", "Control Tower"],
  ["/approvals", "Approval queue"],
  [FITBOX_CASE_PATH, "Aarav Sharma · FitBox Annual"],
  ["/settings", "Recovery policy"],
  ["/lab", "RecoveryBench"],
  ["/voice", "Rehearse every intent before a real call"],
] as const;

test("all merchant routes pass the native semantic and overflow scan", async ({
  page,
}) => {
  for (const [route, heading] of merchantRoutes) {
    await page.goto(route);
    await expect(
      page.getByRole("heading", { level: 1, name: heading }),
    ).toBeVisible();
    await expect.poll(() => scanSemanticAccessibility(page)).toEqual([]);
    await assertNoHorizontalOverflow(page);
  }
});

test("operator can reach the approval decision using only the keyboard", async ({
  page,
}) => {
  await mockMerchantMutations(page);
  await page.goto("/login");
  await tabTo(page, "Work email");
  await page.keyboard.press("Control+A");
  await page.keyboard.type("demo@recoveryos.dev");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Control+A");
  await page.keyboard.type("recovery-demo");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expectMockDashboard(page);

  await tabTo(page, "Skip to main content");
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();

  if ((page.viewportSize()?.width ?? 0) < 700) {
    await tabTo(page, "Open navigation");
    await page.keyboard.press("Enter");
    await expect(page.getByLabel("Mobile navigation")).toHaveAttribute(
      "aria-hidden",
      "false",
    );
  }

  await tabTo(page, "Approval queue");
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/approvals$/);
  await tabTo(page, "Review");
  await page.keyboard.press("Enter");

  const dialog = page.getByRole("alertdialog", {
    name: "Approve this recovery surface?",
  });
  await expect(dialog).toBeVisible();
  await expect(
    dialog.getByRole("button", { name: "Approve exact surface" }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByText("Approval queue is clear")).toBeVisible();
});

test("dialog traps focus and Escape restores the review control", async ({
  page,
}) => {
  await page.goto("/approvals");
  await expect(
    page.getByRole("heading", { level: 1, name: "Approval queue" }),
  ).toBeVisible();
  const review = page.getByRole("button", { name: "Review" });
  await review.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toBeVisible();

  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    dialog.getByRole("button", { name: "Approve exact surface" }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(review).toBeFocused();
});
