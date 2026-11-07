// Main application smoke: verify actual routes and key controls without
// legacy Decision Center paths that are no longer part of App.tsx.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');
const BASE = process.env.ARIA_BASE || 'http://localhost:8000';

test.describe('Current main app controls', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });

  async function navigate(name, hash) {
    const item = page.locator('nav').getByRole('button', { name, exact: true });
    await item.click();
    await expect(item).toHaveAttribute('aria-current', 'page');
    await expect(page).toHaveURL(new RegExp('#/' + hash + '$'));
    await expect(page.locator('main')).not.toBeEmpty({ timeout: 10000 });
  }

  test('Dashboard opens as the initial authenticated route', async () => {
    await navigate('Dashboard', 'dashboard');
    await expect(page.locator('header h1')).toHaveText('Dashboard');
  });

  test('Data page offers connection choices', async () => {
    await navigate('Data', 'data');
    await expect(page.getByText('Choose a data source')).toBeVisible();
  });

  test('Schema is available within the Data workspace', async () => {
    await navigate('Data', 'data');
    await expect(page.locator('header h1')).toHaveText('Data');
  });

  test('AI Analytics loads', async () => {
    await navigate('AI Analytics', 'analytics');
    await expect(page.locator('header h1')).toHaveText('AI Analytics');
  });

  test('Insights loads', async () => {
    await navigate('Insights', 'insights');
    await expect(page.locator('header h1')).toHaveText('Insights');
  });

  test('Forecast loads via predictive route', async () => {
    await navigate('Forecast', 'predictive');
    await expect(page.locator('header h1')).toHaveText('Forecast');
  });

  test('Intelligence workspace replaces retired Decision Center', async () => {
    await navigate('Intelligence', 'intelligence');
    await expect(page.getByRole('heading', { name: 'ARIA Intelligence' })).toBeVisible();
  });

  test('Intelligence has hypotheses and reports tabs', async () => {
    await navigate('Intelligence', 'intelligence');
    await expect(page.getByRole('tab', { name: /^Hypotheses$/i })).toBeVisible();
    await expect(page.getByRole('tab', { name: /^Reports$/i })).toBeVisible();
  });

  test('legacy hypothesis hash resolves to AI Analytics', async () => {
    await page.evaluate(() => { location.hash = '#/hypothesis'; });
    await expect(page.locator('header h1')).toHaveText('AI Analytics');
  });

  test('History loads', async () => {
    await navigate('History', 'history');
    await expect(page.locator('header h1')).toHaveText('History');
  });

  test('Documents loads', async () => {
    await navigate('Documents', 'documents');
    await expect(page.locator('header h1')).toHaveText('Documents');
  });

  test('Settings exposes AI Configuration', async () => {
    await navigate('Settings', 'settings');
    await expect(page.getByText('AI Configuration').first()).toBeVisible();
  });
});
