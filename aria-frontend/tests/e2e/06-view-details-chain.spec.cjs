// Canonical cross-page navigation and deep linking. Removed detail routes
// from the earlier Decision Center UI are not part of the current product.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');
const BASE = process.env.ARIA_BASE || 'http://localhost:8000';

test.describe('Intelligence navigation chain', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });

  test('opens Intelligence from Dashboard and updates route', async () => {
    await page.locator('nav').getByRole('button', { name: 'Dashboard', exact: true }).click();
    await page.locator('nav').getByRole('button', { name: 'Intelligence', exact: true }).click();
    await expect(page).toHaveURL(/#\/intelligence$/);
    await expect(page.getByRole('heading', { name: 'ARIA Intelligence' })).toBeVisible();
  });

  test('navigates from Intelligence to Insights and back', async () => {
    await page.locator('nav').getByRole('button', { name: 'Insights', exact: true }).click();
    await expect(page.locator('header h1')).toHaveText('Insights');
    await page.goBack();
    await expect(page.locator('header h1')).toHaveText('Intelligence');
    await expect(page.getByRole('tab', { name: /^Explore$/i })).toBeVisible();
  });

  test('direct hash navigation retains authenticated page', async () => {
    await page.evaluate(() => { location.hash = '#/intelligence'; });
    await expect(page.locator('header h1')).toHaveText('Intelligence');
    await expect(page.getByRole('tab', { name: /^Reports$/i })).toBeVisible();
  });
});
