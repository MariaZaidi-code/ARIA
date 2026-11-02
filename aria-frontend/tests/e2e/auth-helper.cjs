// Shared Playwright helper: real backend auth + LLM selection.
// Single-host policy: everything runs against http://localhost:8000
// (override with ARIA_E2E_BASE_URL to test an isolated server on another port).
const DEFAULT_BASE = process.env.ARIA_E2E_BASE_URL || 'http://localhost:8000';
// E2E uses a pre-provisioned verified non-admin account so tests exercise
// real cookie auth without bypassing the email-verification requirement.
const { expect } = require('@playwright/test');

async function signInVerified(page, base = DEFAULT_BASE) {
  const email = process.env.ARIA_E2E_EMAIL;
  const pass = process.env.ARIA_E2E_PASSWORD;
  if (!email || !pass) {
    throw new Error(
      'Set ARIA_E2E_EMAIL and ARIA_E2E_PASSWORD to an existing verified non-admin test account.',
    );
  }
  await page.goto(base);
  await page.locator('#login-email').fill(email);
  await page.locator('#login-password').fill(pass);
  await page.getByRole('button', { name: /access intelligence hub/i }).click();
  await page.getByText('Choose your AI engine').waitFor({ timeout: 20000 });
}

async function seedAuth(page, base = DEFAULT_BASE, mode = 'Local AI') {
  await signInVerified(page, base);
  await page.getByText(mode, { exact: false }).first().click();
  await page.getByRole('button', { name: /continue/i }).click();
  // Fail here (not 60s later inside the test body) if the engine switch did
  // not land — every spec's first act assumes the authenticated workspace.
  await expect(page.getByRole('navigation').getByRole('button', { name: /^dashboard$/i }))
    .toBeVisible({ timeout: 20000 });
}

module.exports = { seedAuth, signInVerified };
