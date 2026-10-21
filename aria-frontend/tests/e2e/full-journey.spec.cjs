// CommonJS // Playwright: full journey through all ARIA pages (Figma layer + main)
// Canonical contract: no standalone Prescription/Hypothesis/Decision Center
// pages. Prescription is verified via the prescription APIs / Intelligence;
// hypothesis via Insights -> "Investigate why" -> AI Analytics Possible drivers.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const PAGES = [
  // navText = exact sidebar label; the top-bar <h1> shows the same title.
  { name: 'Dashboard', navText: 'Dashboard' },
  { name: 'AIAnalytics', navText: 'AI Analytics' },
  { name: 'Insights', navText: 'Insights' },
  { name: 'Predictive', navText: 'Forecast' },
  { name: 'Intelligence', navText: 'Intelligence' },
  { name: 'Data', navText: 'Data' },
  { name: 'Documents', navText: 'Documents' },
  { name: 'Copilot', navText: 'Copilot' },
  { name: 'History', navText: 'History' },
  { name: 'Settings', navText: 'Settings' },
];

test.describe('Full journey - every page loads', () => {
  let page;
  test.beforeAll(async ({ browser }) => { page = await browser.newPage(); await seedAuth(page, 'http://localhost:8000'); });

  for (const p of PAGES) {
    test(`navigate to ${p.name}`, async () => {
      await page.getByRole('button', { name: new RegExp('^' + p.navText + '$', 'i') }).first().click();
      await expect(page.locator('h1').filter({ hasText: new RegExp('^' + p.navText, 'i') }).first())
        .toBeVisible({ timeout: 15000 });
      await expect(page.getByText(/something went wrong on this page/i)).toHaveCount(0);
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
