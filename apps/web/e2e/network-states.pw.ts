import { expect, test } from "@playwright/test";

test("dashboard exposes a labelled loading state before the recovery workspace", async ({
  page,
}) => {
  let releaseRequests!: () => void;
  const released = new Promise<void>((resolve) => {
    releaseRequests = resolve;
  });
  await page.route("**/__e2e-api/v1/**", async (route) => {
    await released;
    await route.abort("connectionrefused");
  });

  await page.goto("/dashboard");
  await expect(page.getByLabel("Loading Control Tower")).toBeVisible();
  releaseRequests();
  await expect(
    page.getByRole("heading", { level: 1, name: "Control Tower" }),
  ).toBeVisible();
  await expect(
    page.getByText("Recovery workspace", { exact: true }).first(),
  ).toBeVisible();
});

test("voice transport failure is visible and does not trigger another request", async ({
  page,
}) => {
  let attempts = 0;
  await page.route(
    "**/__e2e-api/v1/voice/contacts/*/browser-transcript",
    async (route) => {
      attempts += 1;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          detail: { code: "VOICE_PROVIDER_UNAVAILABLE" },
        }),
      });
    },
  );
  await page.goto("/voice");
  await page
    .getByPlaceholder("Example: Please stop calling, I will pay tomorrow.")
    .fill("I can pay tomorrow");
  await page.getByRole("button", { name: "Analyze transcript" }).click();
  await expect(page.getByText("Voice action unavailable")).toBeVisible();
  await expect(page.getByText("VOICE_PROVIDER_UNAVAILABLE")).toBeVisible();
  await page.waitForTimeout(250);
  expect(attempts).toBe(1);
});

test("A2A load failure can be retried without changing the requested task", async ({
  page,
}) => {
  const taskId = "e2e-retry-load";
  let attempts = 0;
  await page.route(
    `**/__e2e-agent/v1/tasks/${taskId}/approval`,
    async (route) => {
      attempts += 1;
      if (attempts === 1) {
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({
            detail: "Customer agent temporarily unavailable",
          }),
        });
        return;
      }
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
          payment_surface_reference: "retry_surface",
          expires_at: "2099-08-30T10:00:01Z",
          merchant_display_name: "FitBox",
          recovery_reason: "Failed annual subscription renewal",
        }),
      });
    },
  );

  await page.goto(`/a2a/${taskId}`);
  await expect(
    page.getByRole("heading", { name: "We could not load this request" }),
  ).toBeVisible();
  await expect(
    page.getByText("Customer agent temporarily unavailable"),
  ).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(
    page.getByRole("heading", { name: "Review recovery authorization" }),
  ).toBeVisible();
  expect(attempts).toBe(2);
});
