// Real browser journey through the currently supported navigation graph.
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

test.describe('Full ARIA navigation journey', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });

  for (const { label, id } of PAGES) {
    test('navigate to ' + label, async () => {
      await page.locator('nav').getByRole('button', { name: label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp('#/' + id + '$'));
      await expect(page.locator('header h1')).toContainText(label);
      await expect(page.locator('main')).not.toBeEmpty({ timeout: 10000 });
    });
  }

  test('Insights and Intelligence remain distinct workspaces', async () => {
    await page.locator('nav').getByRole('button', { name: 'Insights', exact: true }).click();
    await expect(page.locator('header h1')).toHaveText('Insights');
    await page.locator('nav').getByRole('button', { name: 'Intelligence', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'ARIA Intelligence' })).toBeVisible();
    await expect(page.getByRole('tab', { name: /^Hypotheses$/i })).toBeVisible();
  });

  test('Reports capability is available inside Intelligence', async () => {
    await page.locator('nav').getByRole('button', { name: 'Intelligence', exact: true }).click();
    await page.getByRole('tab', { name: /^Reports$/i }).click();
    await expect(page.getByLabel('Report name')).toBeVisible();
  });
});
