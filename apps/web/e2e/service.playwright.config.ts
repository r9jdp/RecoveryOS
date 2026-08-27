import { defineConfig, devices } from "@playwright/test";

const webOrigin = process.env.RECOVERYOS_SERVICE_WEB_ORIGIN;
if (!webOrigin) {
  throw new Error("RECOVERYOS_SERVICE_WEB_ORIGIN is required");
}

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.service.pw.ts",
  outputDir: "../../../test-results/service-stack",
  fullyParallel: false,
  forbidOnly: true,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [
        ["line"],
        [
          "html",
          {
            open: "never",
            outputFolder: "../../../playwright-report/service-stack",
          },
        ],
      ]
    : "line",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: webOrigin,
    colorScheme: "light",
    locale: "en-IN",
    serviceWorkers: "block",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "service-chromium",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 960 },
      },
    },
  ],
});
