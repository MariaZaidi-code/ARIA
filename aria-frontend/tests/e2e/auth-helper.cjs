// Shared Playwright helper: real backend auth + LLM selection.
// Single-host policy: everything runs against http://localhost:8000.
// No fake tokens: registers a throwaway user through the real signup form,
// then picks the requested AI engine. Signup already establishes the session.
const { expect } = require('@playwright/test');

async function seedAuth(page, base = 'http://localhost:8000', mode = 'Local AI') {
  const user = 'pw' + Date.now() + Math.floor(Math.random() * 1e6);
  const email = `${user}@aria.test`;
  const pass = 'password123';
  await page.goto(base);
  await page.getByRole('button', { name: /create account/i }).first().click();
  await page.locator('#login-email').fill(email);
  await page.locator('#login-password').fill(pass);
  await page.locator('#login-confirm').fill(pass);
  await page.getByRole('button', { name: /create account/i }).last().click();
  await page.getByText('Choose your AI engine').waitFor({ timeout: 20000 });
  await page.getByText(mode, { exact: false }).first().click();
  await page.getByRole('button', { name: /continue/i }).click();
  // Fail here (not 60s later inside the test body) if the engine switch did
  // not land — every spec's first act assumes the authenticated workspace.
  await expect(page.getByRole('navigation').getByRole('button', { name: /^dashboard$/i }))
    .toBeVisible({ timeout: 20000 });
}

module.exports = { seedAuth };
