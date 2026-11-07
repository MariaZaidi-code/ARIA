// Canonical frontend routes: every current AppShell navigation item loads.
// Authentication and provider switching are real; model generation is not
// required to verify navigation and rendering in headless CI.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');
const BASE = process.env.ARIA_BASE || 'http://localhost:8000';
const PAGES = [
  { label: 'Dashboard', id: 'dashboard' },
  { label: 'AI Analytics', id: 'analytics' },
  { label: 'Insights', id: 'insights' },
  { label: 'Intelligence', id: 'intelligence' },
  { label: 'Forecast', id: 'predictive' },
  { label: 'Data', id: 'data' },
  { label: 'Documents', id: 'documents' },
  { label: 'Copilot', id: 'copilot' },
  { label: 'History', id: 'history' },
  { label: 'Settings', id: 'settings' },
];

test.describe('Current ARIA pages', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });

  for (const { label, id } of PAGES) {
    test(`${label} renders through sidebar navigation`, async () => {
      const item = page.locator('nav').getByRole('button', { name: label, exact: true });
      await item.click();
      await expect(item).toHaveAttribute('aria-current', 'page');
      await expect(page).toHaveURL(new RegExp('#/' + id + '$'));
      await expect(page.locator('header h1')).toContainText(label);
      await expect(page.locator('main')).not.toBeEmpty({ timeout: 10000 });
    });
  }

  test('legacy hypothesis hash routes to AI Analytics', async () => {
    await page.evaluate(() => { location.hash = '#/hypothesis'; });
    await expect(page.locator('header h1')).toContainText('AI Analytics');
  });

  test('Intelligence hash links to the current five-tab workspace', async () => {
    await page.evaluate(() => { location.hash = '#/intelligence'; });
    await expect(page.getByRole('heading', { name: 'ARIA Intelligence' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /^Reports$/i })).toBeVisible();
  });
});
