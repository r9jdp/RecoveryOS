import { defineConfig, devices } from "@playwright/test";

const port = Number(process.env.RECOVERYOS_E2E_PORT ?? "3100");
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.pw.ts",
  testIgnore: ["**/support/**", "**/*.service.pw.ts"],
  outputDir: "test-results",
  snapshotPathTemplate: "{testDir}/snapshots/{projectName}/{arg}{ext}",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : 2,
  reporter: process.env.CI
    ? [["line"], ["html", { open: "never", outputFolder: "playwright-report" }]]
    : "line",
  timeout: 30_000,
  expect: {
    timeout: 7_500,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      maxDiffPixelRatio: 0.005,
    },
  },
  use: {
    baseURL,
    colorScheme: "light",
    locale: "en-IN",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 960 },
      },
    },
    {
      name: "mobile-chromium",
      testMatch: [
        "**/accessibility-keyboard.pw.ts",
        "**/failure-lab.pw.ts",
        "**/visual-regression.pw.ts",
      ],
      use: {
        ...devices["Desktop Chrome"],
        hasTouch: true,
        isMobile: true,
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  webServer: {
    command: `pnpm dev --hostname 127.0.0.1 --port ${port}`,
    cwd: "..",
    env: {
      CUSTOMER_AGENT_ORIGIN: `${baseURL}/__e2e-agent`,
      NEXT_PUBLIC_API_BASE_URL: `${baseURL}/__e2e-api`,
      NEXT_PUBLIC_RECOVERY_API_URL: `${baseURL}/__e2e-api`,
      RECOVERYOS_NEXT_DIST_DIR: ".next-e2e",
    },
    reuseExistingServer: false,
    timeout: 120_000,
    url: `${baseURL}/login`,
  },
});
