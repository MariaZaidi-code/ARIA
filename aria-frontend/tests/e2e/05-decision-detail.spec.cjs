// Current Intelligence hypothesis and evidence workspace.
// The old /decision-center/detail route was removed from App.tsx; these
// assertions target the real Intelligence tabs and honest empty states.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');
const BASE = process.env.ARIA_BASE || 'http://localhost:8000';

test.describe('Intelligence hypothesis and evidence UI', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
    await page.locator('nav').getByRole('button', { name: 'Intelligence', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'ARIA Intelligence' })).toBeVisible();
  });
  test.afterAll(async () => { await page.close(); });

  test('opens the hypothesis investigation workspace', async () => {
    const tab = page.getByRole('tab', { name: /^Hypotheses$/i });
    await tab.click();
    await expect(tab).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('main')).not.toBeEmpty();
  });

  test('reports evidence unavailability without raw Python tracebacks', async () => {
    await page.getByRole('tab', { name: /^Hypotheses$/i }).click();
    await expect(page.locator('main')).not.toContainText(/Traceback \(most recent call last\)|ModuleNotFoundError|\[object Object\]/i);
  });

  test('navigates from hypotheses to Explore', async () => {
    await page.getByRole('tab', { name: /^Explore$/i }).click();
    await expect(page.getByRole('tab', { name: /^Explore$/i })).toHaveAttribute('aria-selected', 'true');
    await expect(page.getByLabel('Metric')).toBeVisible();
  });

  test('goal creation form is accessible', async () => {
    await page.getByRole('tab', { name: /^Goals$/i }).click();
    await page.getByRole('button', { name: /^Create goal$/i }).first().click();
    await expect(page.getByLabel('Goal title')).toBeVisible();
    await expect(page.getByLabel('Target value')).toBeVisible();
  });

  test('What-If tab renders its setup or no-source explanation', async () => {
    await page.getByRole('tab', { name: /^What-If$/i }).click();
    await expect(page.getByRole('tab', { name: /^What-If$/i })).toHaveAttribute('aria-selected', 'true');
    await expect(page.locator('main')).not.toBeEmpty();
  });

  test('Reports tab includes a named report form', async () => {
    await page.getByRole('tab', { name: /^Reports$/i }).click();
    await expect(page.getByLabel('Report name')).toBeVisible();
    await expect(page.getByLabel('Report description')).toBeVisible();
  });

  test('returning to Hypotheses preserves the workspace', async () => {
    await page.getByRole('tab', { name: /^Hypotheses$/i }).click();
    await expect(page.locator('header h1')).toHaveText('Intelligence');
    await expect(page.getByRole('tab', { name: /^Hypotheses$/i })).toHaveAttribute('aria-selected', 'true');
  });
});
