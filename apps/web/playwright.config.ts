import { defineConfig, devices } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  retries: 0,
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.CDF_WEB_ORIGIN || "http://127.0.0.1:5173",
    trace: "off",
    launchOptions: {
      executablePath: process.env.CDF_CHROMIUM_EXECUTABLE || undefined,
    },
  },
  webServer: {
    command: "npm run dev -- --port " + (process.env.CDF_WEB_PORT || "5173"),
    url: process.env.CDF_WEB_ORIGIN || "http://127.0.0.1:5173",
    timeout: 60_000,
    reuseExistingServer: !process.env.CI,
  },
});
