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

    const password = page.locator('#login-password');
    await expect(password).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: 'Show password' }).click();
    await expect(password).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: 'Hide password' }).click();
    await expect(password).toHaveAttribute('type', 'password');
  });
  test('configured admin lands on the separate admin dashboard', async ({ page }) => {
    await page.route('**/api/auth/register', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true, verification_required: true,
        message: 'Check your email for a verification link before signing in.',
      }),
    }));
    await page.route('**/api/auth/verify-email', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, message: 'Email verified. You can now sign in.' }),
    }));
    await page.route('**/api/auth/login', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true, username: 'admin@example.com', email: 'admin@example.com',
        user_id: 42, is_admin: true,
      }),
    }));
    await page.route('**/api/admin/page-visit', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    }));
    await page.route('**/api/admin/overview', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        overview: {
          users_total: 12,
          users_new_7d: 2,
          analyses_total: 48,
          analyses_7d: 9,
          active_users_7d: 5,
          last_activity: '2026-10-20T12:00:00+00:00',
          logins_total: 22,
          logins_7d: 5,
          page_visits_total: 140,
          page_visits_7d: 33,
          page_visits_by_page: [],
          recent_events: [],
          system: { api: 'available', auth_store: 'available' },
        },
      }),
    }));
    await page.route('**/api/workspace/notifications', (route) => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, items: [], unread: 0 }),
    }));

    await page.goto(BASE);
    await page.getByRole('button', { name: 'Create Account', exact: true }).click();
    await page.locator('#login-email').fill('admin@example.com');
    await page.locator('#login-password').fill('SecurePass123!');
    await page.locator('#login-confirm').fill('SecurePass123!');
    await page.getByRole('button', { name: /Create Account/ }).click();
    await expect(page.getByRole('status')).toContainText('Check your email');

    await page.goto(`${BASE}/?verify_email=playwright-test-token`);
    await expect(page.getByRole('status')).toContainText('Email verified');
    await page.locator('#login-email').fill('admin@example.com');
    await page.locator('#login-password').fill('SecurePass123!');
    await page.getByRole('button', { name: /Access Intelligence Hub/ }).click();

    await expect(page.getByRole('heading', { name: 'Admin Dashboard' }).last()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Admin Dashboard' })).toBeVisible();
    await expect(page.getByText('Registered users')).toBeVisible();
    await expect(page.getByText('12', { exact: true })).toBeVisible();
    await expect(page.getByText('System status')).toBeVisible();
  });
  test('verified user sign-in opens the workspace', async ({ page }) => {
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
