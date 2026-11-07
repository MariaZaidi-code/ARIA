const { defineConfig } = require("@playwright/test");

module.exports = defineConfig({
  testDir: "./tests/e2e",
  // The wiring-audit suite has its own config and dataset prerequisites
  // (work/datasets + PostgreSQL); never run it as part of the main gate.
  testIgnore: ["audit/**"],
  timeout: 120000,
  retries: 0,
  workers: 1,
  use: {
    baseURL: process.env.ARIA_E2E_BASE_URL || "http://localhost:8000",
    headless: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    viewport: { width: 1280, height: 800 },
  },
  reporter: [["list"], ["html", { open: "never" }]],
});
