import { expect, type Page, type TestInfo } from "@playwright/test";

export const FITBOX_CASE_ID = "case_fitbox_aug_2026";
export const FITBOX_CASE_PATH = `/cases/${FITBOX_CASE_ID}`;
export const A2A_APPROVAL_TASK_ID = "e2e-a2a-capability";
export const A2A_APPROVAL_TOKEN = "e2e-a2a-capability-token";
export const A2A_APPROVAL_PATH = `/a2a/${A2A_APPROVAL_TASK_ID}#token=${A2A_APPROVAL_TOKEN}`;

export async function mockA2AApproval(page: Page): Promise<void> {
  await page.route(
    `**/__e2e-agent/v1/tasks/${A2A_APPROVAL_TASK_ID}/approval`,
    async (route) => {
      const request = route.request();
      expect(request.headers().authorization).toBe(
        `Bearer ${A2A_APPROVAL_TOKEN}`,
      );

      if (request.method() === "GET") {
        await route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({
            task_id: A2A_APPROVAL_TASK_ID,
            state: "TASK_STATE_AUTH_REQUIRED",
            merchant_id: "merchant_fitbox",
            case_id: FITBOX_CASE_ID,
            exact_amount_paise: 149_900,
            currency: "INR",
            payment_surface_type: "SUBSCRIPTION_INVOICE_LINK",
            payment_surface_reference: "inv_fitbox_aug_2026",
            expires_at: "2099-09-01T12:00:00Z",
            merchant_display_name: "FitBox",
            plan_name: "FitBox Annual",
            failure_explanation:
              "The renewal failed and needs the customer to complete payment.",
          }),
        });
        return;
      }

      expect(request.method()).toBe("POST");
      expect(request.postDataJSON()).toEqual({
        decision: "APPROVE",
        merchant_id: "merchant_fitbox",
        case_id: FITBOX_CASE_ID,
        exact_amount_paise: 149_900,
        payment_surface_reference: "inv_fitbox_aug_2026",
      });
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          id: A2A_APPROVAL_TASK_ID,
          status: { state: "TASK_STATE_WORKING" },
        }),
      });
    },
  );
}

export async function expectMockDashboard(page: Page): Promise<void> {
  await expect(
    page.getByRole("heading", { level: 1, name: "Control Tower" }),
  ).toBeVisible();
  await expect(page.getByText("Demo data active")).toBeVisible();
  await expect(
    page.getByText("Seeded demo data", { exact: true }).first(),
  ).toBeVisible();
}

export async function openMockDashboard(page: Page): Promise<void> {
  await page.goto("/dashboard");
  await expectMockDashboard(page);
}

export async function mockMerchantMutations(page: Page): Promise<void> {
  await page.route("**/__e2e-api/v1/operator/session", async (route) => {
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        csrf_token: "e2e-fixture-csrf-token",
        expires_at_epoch: 2_000_000_000,
        operator: "demo@recoveryos.dev",
      }),
    });
  });
  await page.route(
    "**/__e2e-api/v1/recovery-cases/*/commands",
    async (route) => {
      const body = route.request().postDataJSON() as { command: string };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          command: body.command,
          message:
            "The command was accepted by the mock provider. No external action was taken.",
          occurred_at: "2026-08-28T10:00:00Z",
          status: "ACCEPTED",
        }),
      });
    },
  );
  await page.route(
    "**/__e2e-api/v1/recovery-cases/*/safety-dispositions",
    async (route) => {
      const body = route.request().postDataJSON() as { disposition: string };
      await route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({
          disposition: body.disposition,
          message: `${body.disposition.replaceAll("_", " ")} recorded in local demo mode. No provider action was taken.`,
          occurred_at: "2026-08-28T10:00:00Z",
          status: "ACCEPTED",
        }),
      });
    },
  );
  await page.route("**/__e2e-api/v1/policy-settings", async (route) => {
    if (route.request().method() !== "PUT") {
      await route.fulfill({ status: 503, body: "mock policy read fallback" });
      return;
    }
    await route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(route.request().postDataJSON()),
    });
  });
}

export async function assertNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(
    dimensions.clientWidth + 1,
  );
}

export async function captureEvidence(
  page: Page,
  testInfo: TestInfo,
  filename: string,
): Promise<void> {
  if (process.env.RECOVERYOS_CAPTURE_EVIDENCE !== "1") return;
  await page.screenshot({
    animations: "disabled",
    fullPage: true,
    path: `public/evidence/phase-5/${testInfo.project.name}-${filename}`,
  });
}

export async function prepareVisualPage(page: Page): Promise<void> {
  // Next's development indicator is test-runner chrome, not RecoveryOS UI.
  await page.addStyleTag({
    content: "nextjs-portal { display: none !important; }",
  });
}

export interface SemanticIssue {
  code: string;
  target: string;
}

export async function scanSemanticAccessibility(
  page: Page,
): Promise<SemanticIssue[]> {
  return page.evaluate(() => {
    const issues: Array<{ code: string; target: string }> = [];
    const identify = (element: Element) => {
      const id = element.getAttribute("id");
      const name = element.getAttribute("name");
      return `${element.tagName.toLowerCase()}${id ? `#${id}` : ""}${name ? `[name=${name}]` : ""}`;
    };
    const visible = (element: Element) => {
      if (element.closest('[aria-hidden="true"]')) return false;
      const html = element as HTMLElement;
      const style = window.getComputedStyle(html);
      return (
        style.display !== "none" &&
        style.visibility !== "hidden" &&
        html.getClientRects().length > 0
      );
    };
    const hasAccessibleText = (element: Element) =>
      Boolean(
        element.getAttribute("aria-label")?.trim() ||
        element.getAttribute("aria-labelledby")?.trim() ||
        element.getAttribute("title")?.trim() ||
        element.textContent?.trim(),
      );

    if (document.documentElement.lang !== "en")
      issues.push({ code: "document-language", target: "html" });
    if (!document.title.trim())
      issues.push({ code: "document-title", target: "head > title" });
    if (!document.querySelector("main"))
      issues.push({ code: "main-landmark", target: "body" });
    if (!document.querySelector("h1"))
      issues.push({ code: "page-heading", target: "body" });

    const ids = new Map<string, number>();
    for (const element of document.querySelectorAll("[id]")) {
      const id = element.id;
      ids.set(id, (ids.get(id) ?? 0) + 1);
    }
    for (const [id, count] of ids) {
      if (count > 1) issues.push({ code: "duplicate-id", target: `#${id}` });
    }

    for (const element of document.querySelectorAll<HTMLElement>(
      "button, a[href]",
    )) {
      if (visible(element) && !hasAccessibleText(element))
        issues.push({ code: "interactive-name", target: identify(element) });
    }

    for (const control of document.querySelectorAll<
      HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
    >("input:not([type=hidden]), select, textarea")) {
      if (!visible(control)) continue;
      const labelled = Boolean(
        control.labels?.length ||
        control.getAttribute("aria-label")?.trim() ||
        control.getAttribute("aria-labelledby")?.trim() ||
        control.getAttribute("title")?.trim(),
      );
      if (!labelled)
        issues.push({ code: "form-control-name", target: identify(control) });
    }

    for (const image of document.querySelectorAll("img")) {
      if (!image.hasAttribute("alt"))
        issues.push({ code: "image-alt", target: identify(image) });
    }

    for (const element of document.querySelectorAll<HTMLElement>(
      "[tabindex]",
    )) {
      if (element.tabIndex > 0)
        issues.push({ code: "positive-tabindex", target: identify(element) });
    }

    for (const element of document.querySelectorAll<HTMLElement>(
      "[aria-labelledby], [aria-describedby]",
    )) {
      for (const attribute of ["aria-labelledby", "aria-describedby"]) {
        const references =
          element.getAttribute(attribute)?.trim().split(/\s+/) ?? [];
        for (const reference of references) {
          if (reference && !document.getElementById(reference))
            issues.push({
              code: "broken-aria-reference",
              target: `${identify(element)}[${attribute}=${reference}]`,
            });
        }
      }
    }

    if (
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth + 1
    )
      issues.push({ code: "horizontal-overflow", target: "html" });
    return issues;
  });
}

export async function tabTo(
  page: Page,
  accessibleName: string,
  maximumTabs = 40,
): Promise<void> {
  for (let index = 0; index < maximumTabs; index += 1) {
    await page.keyboard.press("Tab");
    const matches = await page.evaluate((name) => {
      const active = document.activeElement as HTMLElement | null;
      if (!active) return false;
      if (
        !["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"].includes(active.tagName)
      )
        return false;
      const associatedLabels =
        active instanceof HTMLInputElement ||
        active instanceof HTMLSelectElement ||
        active instanceof HTMLTextAreaElement
          ? Array.from(active.labels ?? [])
              .map((label) => label.textContent)
              .join(" ")
          : "";
      const label =
        active.getAttribute("aria-label") ||
        associatedLabels ||
        active.innerText ||
        active.textContent ||
        active.getAttribute("name") ||
        "";
      return label.trim().replace(/\s+/g, " ").includes(name);
    }, accessibleName);
    if (matches) return;
  }
  throw new Error(`Could not reach ${accessibleName} using Tab`);
}
