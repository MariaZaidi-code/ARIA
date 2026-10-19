// CommonJS // Playwright e2e: Authentication flow (fixed)
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const BASE = 'http://localhost:8000';

test.describe('Auth flow (fixed)', () => {
  test('login page loads with inputs', async ({ page }) => {
    await page.goto('http://localhost:8000');
    await page.waitForLoadState('networkidle');
    const inputs = await page.locator('input').count();
    expect(inputs).toBeGreaterThan(0);
  });
  test('real signup establishes a session and opens the workspace', async ({ page }) => {
    await seedAuth(page, BASE);
    await expect(page.getByRole('navigation').getByRole('button', { name: /^dashboard$/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /^Dashboard$/i })).toBeVisible();
  });

  test('session survives a browser reload', async ({ page }) => {
    await seedAuth(page, BASE);
    const before = await page.context().cookies(BASE);
    let sessionStatus = null;
    page.on('response', (response) => {
      if (new URL(response.url()).pathname === '/api/session/status') sessionStatus = response.status();
    });
    await page.reload();
    await page.waitForTimeout(500);
    const after = await page.context().cookies(BASE);
    const sessionCheck = {
      authCookieBeforeReload: before.some((cookie) => cookie.name === 'aria_token'),
      authCookieAfterReload: after.some((cookie) => cookie.name === 'aria_token'),
      sessionStatusAfterReload: sessionStatus,
    };
    console.log('SESSION_CHECK=' + JSON.stringify(sessionCheck));
    await test.info().attach('session-persistence-check.json', {
      body: JSON.stringify(sessionCheck, null, 2), contentType: 'application/json',
    });
    await expect(page.getByRole('navigation').getByRole('button', { name: /^dashboard$/i })).toBeVisible();
  });
});
