// CommonJS // Playwright: full journey through all ARIA pages (Figma layer + main)
const { test, expect } = require('@playwright/test');

const PAGES = [
  { name: 'Dashboard', navText: 'Dashboard', check: () => expect(page.locator('h2')).toContainText('Dashboard') },
  { name: 'AIAnalytics', navText: 'AI Analytics', check: () => expect(page.locator('h2')).toContainText('Analytics') },
  { name: 'Insights', navText: 'Insights', check: () => expect(page.locator('h2')).toContainText('Insight') },
  { name: 'Predictive', navText: 'Predictive', check: () => expect(page.locator('h2')).toContainText('Predictive') },
  { name: 'Prescription', navText: 'Prescription', check: () => expect(page.locator('h2')).toContainText('Prescription') },
  { name: 'Hypothesis', navText: 'Hypothesis', check: () => expect(page.locator('h2')).toContainText('Hypothesis') },
  { name: 'Data', navText: 'Data', check: () => expect(page.locator('.premium-card')).toBeVisible({ timeout: 5000 }) },
  { name: 'Documents', navText: 'Documents', check: () => expect(page.locator('.premium-card, h2')).toBeVisible({ timeout: 5000 }) },
  { name: 'Copilot', navText: 'Copilot', check: () => expect(page.locator('textarea, input')).toBeVisible({ timeout: 5000 }) },
  { name: 'History', navText: 'History', check: () => expect(page.locator('h2')).toContainText('History') },
  { name: 'Settings', navText: 'Settings', check: () => expect(page.locator('.nav-item')).toHaveCount(7) },
];

test.describe('Full journey - every page loads', () => {
  let page;
  test.beforeAll(async ({ browser }) => { page = await browser.newPage(); await page.goto('http://localhost:5174'); await page.waitForLoadState('networkidle'); });

  for (const p of PAGES) {
    test(`navigate to ${p.name}`, async () => {
      await page.getByRole('button', { name: new RegExp(p.navText, 'i') }).click();
      await page.waitForTimeout(300);
      await p.check();
    });
  }
});
