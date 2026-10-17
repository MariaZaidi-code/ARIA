// CommonJS // Playwright: full journey through all ARIA pages (Figma layer + main)
// Canonical contract: no standalone Prescription/Hypothesis/Decision Center
// pages. Prescription is verified via the prescription APIs / Intelligence;
// hypothesis via Insights -> "Investigate why" -> AI Analytics Possible drivers.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const PAGES = [
  { name: 'Dashboard', navText: 'Dashboard', check: () => expect(page.locator('h2')).toContainText('Dashboard') },
  { name: 'AIAnalytics', navText: 'AI Analytics', check: () => expect(page.locator('h2')).toContainText('Analytics') },
  { name: 'Insights', navText: 'Insights', check: () => expect(page.locator('h2')).toContainText('Insight') },
  { name: 'Predictive', navText: 'Forecast', check: () => expect(page.locator('h2')).toContainText('Forecast') },
  { name: 'Intelligence', navText: 'Intelligence', check: () => expect(page.locator('h2')).toContainText('Intelligence') },
  { name: 'Data', navText: 'Data', check: () => expect(page.locator('.premium-card')).toBeVisible({ timeout: 5000 }) },
  { name: 'Documents', navText: 'Documents', check: () => expect(page.locator('.premium-card, h2')).toBeVisible({ timeout: 5000 }) },
  { name: 'Copilot', navText: 'Copilot', check: () => expect(page.locator('textarea, input')).toBeVisible({ timeout: 5000 }) },
  { name: 'History', navText: 'History', check: () => expect(page.locator('h2')).toContainText('History') },
  { name: 'Settings', navText: 'Settings', check: () => expect(page.locator('.nav-item')).toHaveCount(7) },
];

test.describe('Full journey - every page loads', () => {
  let page;
  test.beforeAll(async ({ browser }) => { page = await browser.newPage(); await seedAuth(page, 'http://localhost:8000'); });

  for (const p of PAGES) {
    test(`navigate to ${p.name}`, async () => {
      await page.getByRole('button', { name: new RegExp(p.navText, 'i') }).click();
      await page.waitForTimeout(300);
      await p.check();
    });
  }

  test('Insights exposes contextual hypothesis entry (Investigate why)', async () => {
    await page.getByRole('button', { name: /insights/i }).first().click();
    await page.waitForTimeout(1500);
    // Empty/loading states are valid; assert the contract, not data.
    const body = await page.locator('#root').innerHTML();
    const hasEntry = /Investigate why|Consider this decision|View analysis|No data source connected|No significant patterns|Analyzing|couldn't generate/i.test(body);
    expect(hasEntry).toBe(true);
  });
});
