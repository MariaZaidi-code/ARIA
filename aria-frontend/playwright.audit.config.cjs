// Audit run (wiring verification). Separate from playwright.config.cjs so the
// existing suite is untouched. Runs ONLY against an isolated test server
// (empty data folder) - never against a server holding real data.
//
// Uses the Google Chrome already installed on this machine (channel
// "chrome"), so no browser download is needed. Override with
// ARIA_AUDIT_CHANNEL=msedge to use Microsoft Edge instead.
//   npx playwright test -c playwright.audit.config.cjs --project=audit
//   npx playwright test -c playwright.audit.config.cjs --project=existing
const { defineConfig } = require("@playwright/test");

const channel = process.env.ARIA_AUDIT_CHANNEL || "chrome";

module.exports = defineConfig({
  outputDir: "./test-results-audit",
  timeout: 240000,
  expect: { timeout: 20000 },
  retries: 0,
  workers: 1,
  use: {
    baseURL: process.env.ARIA_BASE || "http://localhost:8000",
    channel,
    headless: true,
    viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    video: "off",
  },
  projects: [
    { name: "audit", testDir: "./tests/e2e/audit" },
    // The team's existing specs, unchanged, on the same isolated server.
    { name: "existing", testDir: "./tests/e2e", testIgnore: ["audit/**"], timeout: 120000 },
  ],
  reporter: [
    ["list"],
    ["json", { outputFile: "test-results-audit/results.json" }],
    ["html", { outputFolder: "playwright-report-audit", open: "never" }],
  ],
});
