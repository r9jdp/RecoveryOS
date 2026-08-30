import { expect, test } from "@playwright/test";

import { FITBOX_CASE_PATH, mockMerchantMutations } from "./support/fixtures";

test("opt-out is confirmed before suppression and immediately changes disposition", async ({
  page,
}) => {
  await mockMerchantMutations(page);
  await page.goto(FITBOX_CASE_PATH);
  await expect(page.getByText("Seeded demo data").first()).toBeVisible();

  await page.getByRole("button", { name: "Record opt-out" }).click();
  const dialog = page.getByRole("alertdialog", {
    name: "Suppress all customer outreach?",
  });
  await expect(dialog).toContainText(
    "persist this disposition before cancelling",
  );
  await dialog
    .getByRole("button", { name: "Confirm safety disposition" })
    .click();

  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "Mark Opt Out recorded" })
      .first(),
  ).toBeVisible();
  await expect(page.getByText("Opted Out", { exact: true })).toBeVisible();
  await expect(
    page
      .getByRole("status")
      .filter({ hasText: "No provider action was taken." })
      .first(),
  ).toBeVisible();
});

test("already-paid statement pauses action without claiming proof", async ({
  page,
}) => {
  await mockMerchantMutations(page);
  await page.goto(FITBOX_CASE_PATH);
  await expect(page.getByText("Seeded demo data").first()).toBeVisible();

  await page
    .getByRole("button", { name: "Customer says already paid" })
    .click();
  const dialog = page.getByRole("alertdialog", {
    name: "Pause and reconcile payment?",
  });
  await expect(dialog).toContainText("not authoritative proof of payment");
  await dialog
    .getByRole("button", { name: "Confirm safety disposition" })
    .click();
  await expect(page.getByText("Already Paid", { exact: true })).toBeVisible();
});

test("kill switch blocks new actions while reconciliation remains described", async ({
  page,
}) => {
  await mockMerchantMutations(page);
  await page.goto("/settings");
  await expect(
    page.getByRole("heading", { level: 1, name: "Recovery policy" }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Pause all recovery actions" })
    .click();
  const dialog = page.getByRole("alertdialog", {
    name: "Pause all recovery actions?",
  });
  await expect(dialog).toContainText("payment reconciliation remain enabled");
  await dialog.getByRole("button", { name: "Turn on kill switch" }).click();
  await expect(page.getByText("Global kill switch is on")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Resume recovery actions" }),
  ).toBeVisible();
});

test("voice intent precedence ends contact on opt-out and never submits a real call", async ({
  page,
}) => {
  let voiceContacts = 0;
  await page.route("**/__e2e-api/v1/voice/**", async (route) => {
    const request = route.request();
    if (request.url().endsWith("/browser-transcript")) {
      const body = request.postDataJSON() as { transcript: string };
      expect(body.transcript).toContain("stop calling");
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          contact_must_end: true,
          detected_intent: "OPT_OUT",
          disposition: "OPTED_OUT",
          suppression_persisted: true,
        }),
      });
      return;
    }
    if (request.method() === "POST") voiceContacts += 1;
    await route.fulfill({ status: 500, body: "unexpected voice request" });
  });

  await page.goto("/voice");
  await page
    .getByPlaceholder("Example: Please stop calling, I will pay tomorrow.")
    .fill("I will pay tomorrow, but please stop calling me now.");
  await page.getByRole("button", { name: "Analyze transcript" }).click();
  await expect(page.getByText("Detected: OPT OUT")).toBeVisible();
  await expect(page.getByText("Contact must end now")).toBeVisible();
  expect(voiceContacts).toBe(0);
});

test("guarded call is disabled until operator confirmation and exposes no auto-retry", async ({
  page,
}) => {
  await page.route("**/__e2e-api/v1/voice/contacts", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        attempt_id: "voice_e2e_rejected",
        provider: "mock",
        status: "REJECTED",
        reason_code: "REAL_CALLS_DISABLED",
        provider_call_id: null,
        retry_permitted: false,
      }),
    });
  });
  await page.goto("/voice");

  const requestButton = page.getByRole("button", {
    name: "Request guarded test call",
  });
  await expect(requestButton).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: "I am an authorized operator using an allowlisted test number.",
    })
    .check();
  await requestButton.click();
  await expect(page.getByText("Call rejected")).toBeVisible();
  await expect(page.getByText("Automatic retry is disabled.")).toBeVisible();
});

test("A2A approval sends the exact reviewed scope and reports a saved mandate", async ({
  page,
}) => {
  const taskId = "e2e-exact-scope";
  let submitted: Record<string, unknown> | null = null;
  await page.route(
    `**/__e2e-agent/v1/tasks/${taskId}/approval`,
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            task_id: taskId,
            state: "TASK_STATE_AUTH_REQUIRED",
            merchant_id: "merchant_fitbox",
            case_id: "case_fitbox_aug_2026",
            exact_amount_paise: 149_900,
            currency: "INR",
            payment_surface_type: "SUBSCRIPTION_CARD_UPDATE",
            payment_surface_reference: "card_update_fitbox_aug_2026",
            expires_at: "2099-08-30T10:00:01Z",
            merchant_display_name: "FitBox",
            recovery_reason: "Failed annual subscription renewal",
          }),
        });
        return;
      }
      submitted = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          id: taskId,
          status: { state: "TASK_STATE_COMPLETED" },
        }),
      });
    },
  );

  await page.goto(`/a2a/${taskId}`);
  await expect(
    page.getByRole("heading", {
      level: 1,
      name: "Review recovery authorization",
    }),
  ).toBeVisible();
  await expect(page.getByText("₹1,499.00").first()).toBeVisible();
  await expect(page.getByText("No charge happens on this page.")).toBeVisible();

  const approve = page.getByRole("button", { name: "Approve exact surface" });
  await expect(approve).toBeDisabled();
  await page
    .getByRole("checkbox", {
      name: "I approve this exact ₹1,499.00 payment surface.",
    })
    .check();
  await approve.click();
  await expect(
    page.getByRole("heading", { level: 1, name: "Authorization recorded" }),
  ).toBeVisible();
  expect(submitted).toEqual({
    decision: "APPROVE",
    merchant_id: "merchant_fitbox",
    case_id: "case_fitbox_aug_2026",
    exact_amount_paise: 149_900,
    payment_surface_reference: "card_update_fitbox_aug_2026",
  });
});

test("A2A replay rejection leaves the decision unsaved", async ({ page }) => {
  const taskId = "e2e-replay";
  await page.route(
    `**/__e2e-agent/v1/tasks/${taskId}/approval`,
    async (route) => {
      if (route.request().method() === "GET") {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            task_id: taskId,
            state: "TASK_STATE_AUTH_REQUIRED",
            merchant_id: "merchant_fitbox",
            case_id: "case_fitbox_aug_2026",
            exact_amount_paise: 149_900,
            currency: "INR",
            payment_surface_type: "SUBSCRIPTION_CARD_UPDATE",
            payment_surface_reference: "card_update_replayed",
            expires_at: "2099-08-30T10:00:01Z",
            merchant_display_name: "FitBox",
            recovery_reason: "Failed annual subscription renewal",
          }),
        });
        return;
      }
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Mandate nonce has already been consumed",
        }),
      });
    },
  );

  await page.goto(`/a2a/${taskId}`);
  await page.getByRole("checkbox", { name: /I approve this exact/ }).check();
  await page.getByRole("button", { name: "Approve exact surface" }).click();
  await expect(page.getByText("Your decision was not saved")).toBeVisible();
  await expect(
    page.getByText("Mandate nonce has already been consumed"),
  ).toBeVisible();
  await expect(page.getByText("Decision saved")).toHaveCount(0);
});
