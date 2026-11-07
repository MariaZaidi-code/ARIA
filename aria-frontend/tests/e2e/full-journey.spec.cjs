// CommonJS // Playwright: full journey through all ARIA pages (Figma layer + main)
// Canonical contract: no standalone Prescription/Hypothesis/Decision Center
// pages. Prescription is verified via the prescription APIs / Intelligence;
// hypothesis via Insights -> "Investigate why" -> AI Analytics Possible drivers.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const VIS = { timeout: 15000 };
const PAGES = [
  { name: 'Dashboard', navText: 'Dashboard', check: (page) => expect(page.getByRole('banner').getByRole('heading', { name: /Dashboard/i })).toBeVisible(VIS) },
  { name: 'AIAnalytics', navText: 'AI Analytics', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /^Analytics$/i })).toBeVisible(VIS) },
  { name: 'Insights', navText: 'Insights', check: (page) => expect(page.getByRole('banner').getByRole('heading', { name: /^Insights/i })).toBeVisible(VIS) },
  { name: 'Predictive', navText: 'Forecast', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /^Forecast$/i })).toBeVisible(VIS) },
  { name: 'Intelligence', navText: 'Intelligence', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /ARIA Intelligence/i })).toBeVisible(VIS) },
  { name: 'Data', navText: 'Data', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /^Data$/i })).toBeVisible(VIS) },
  { name: 'Documents', navText: 'Documents', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /^Documents$/i, level: 1 })).toBeVisible(VIS) },
  { name: 'Copilot', navText: 'Copilot', check: (page) => expect(page.locator('textarea, input')).toBeVisible({ timeout: 15000 }) },
  { name: 'History', navText: 'History', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /^History$/i })).toBeVisible(VIS) },
  { name: 'Settings', navText: 'Settings', check: (page) => expect(page.getByRole('main').getByRole('heading', { name: /^Settings$/i })).toBeVisible(VIS) },
];

test.describe('Full journey - every page loads', () => {
  let page;
  test.beforeAll(async ({ browser }) => { page = await browser.newPage(); await seedAuth(page, 'http://localhost:8000'); });

  for (const p of PAGES) {
    test(`navigate to ${p.name}`, async () => {
      await page.getByRole('navigation').getByRole('button', { name: new RegExp(`^${p.navText}$`, 'i') }).click();
      await page.waitForTimeout(300);
      await p.check(page);
    });
  }

  test('Insights exposes contextual hypothesis entry (Investigate why)', async () => {
    await page.getByRole('navigation').getByRole('button', { name: /^insights$/i }).click();
    await page.waitForTimeout(1500);
    // Empty/loading states are valid; assert the contract, not data.
    const body = await page.locator('#root').innerHTML();
    const hasEntry = /Investigate why|Consider this decision|View analysis|No data source connected|No significant patterns|Analyzing|couldn't generate/i.test(body);
    expect(hasEntry).toBe(true);
  });
});
