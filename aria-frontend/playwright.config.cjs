// CommonJS Playwright config
const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests/e2e',
  timeout: 30000,
  retries: 0,
  use: {
    baseURL: 'http://localhost:5174',
    headless: true,
  },
  webServer: {
    command: 'npm run dev',
    port: 5174,
    reuseExistingServer: true,
    timeout: 30000,
  },
  reporter: 'line',
});
