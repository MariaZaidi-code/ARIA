// Shared E2E helper: real backend registration, UI login, cookie auth and
// provider selection. No fake JWTs or simulated backend login.
const { expect } = require('@playwright/test');

async function seedAuth(page, base = 'http://localhost:8000', mode = 'Local AI', options = {}) {
  const user = 'pw' + Date.now() + Math.floor(Math.random() * 1e6);
  const email = user + '@aria.test';
  const password = 'password123';
  // Match authStorage.js: normalizeEmail().replace(/@/g, '_at_').
  const backendUsername = user + '_at_aria.test';

  // Browser-only CI fixture: Ollama is not installed on hosted CI runners.
  // We test genuine login and provider-switch API, but NOT model inference.
  // Only the advisory availability display is overridden for Local AI.
  if (process.env.CI) {
    await page.route('**/api/providers/status', async route => {
      const upstream = await route.fetch();
      if (!upstream.ok()) return route.fulfill({ response: upstream });
      const payload = await upstream.json();
      for (const item of payload.providers || []) {
        if (item.provider === 'local') {
          item.available = true;
          item.reason = 'Browser UI test fixture; Ollama generation is not exercised.';
        }
      }
      return route.fulfill({
        response: upstream,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      });
    });
  }

  const registered = await page.request.post(base + '/api/auth/register', {
    data: { username: backendUsername, password },
  });
  if (!registered.ok()) {
    throw new Error('E2E registration failed (' + registered.status() + '): ' +
      (await registered.text()).slice(0, 200));
  }

  await page.goto(base);
  await expect(page.locator('#login-email')).toBeVisible();
  await page.locator('#login-email').fill(email);
  await page.locator('#login-password').fill(password);
  await page.locator('.login-button').click();
  await expect(page.getByRole('heading', { name: 'Choose your AI engine' }))
    .toBeVisible({ timeout: 20000 });

  // Check a genuine session cookie is usable by the real backend.
  const identity = await page.request.get(base + '/api/auth/me');
  expect(identity.ok(), 'Real login must establish a valid session cookie').toBeTruthy();

  if (options.stopAtSelection) return { email, username: backendUsername };
  if (mode !== 'Local AI') {
    throw new Error('Hosted engines require real API credentials; use stopAtSelection to test Cloud UI.');
  }

  await page.getByRole('button', { name: /Local AI/i }).first().click();
  await page.getByRole('button', { name: /^Continue$/i }).click();
  await expect(page.getByRole('button', { name: /^Dashboard$/i }).first())
    .toBeVisible({ timeout: 20000 });
  return { email, username: backendUsername };
}

module.exports = { seedAuth };
