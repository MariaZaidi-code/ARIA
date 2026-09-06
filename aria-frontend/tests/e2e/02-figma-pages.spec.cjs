// CommonJS // Playwright e2e: All figma pages load without errors
// Requires user to be logged in (seed auth token in localStorage before running,
// or skip if already authenticated).
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:5174';

/** Seed a fake auth token so figma pages render (real auth tested separately). */
async function seedAuth(page) {
  await page.goto(BASE);
  await page.evaluate(() => {
    localStorage.setItem('aria_auth_token', 'test_token_playwright_2024');
    localStorage.setItem('aria_auth_user', JSON.stringify({ email: 'test@aria.ai', username: 'TestUser' }));
    localStorage.setItem('aria_llm_mode', 'local');
  });
}

test.describe('Figma pages - all load', () => {
  for (const { name, nav, heading, selector } of [
    { name: 'Dashboard',    nav: 'Dashboard',     heading: 'Dashboard',         selector: 'text=Welcome' },
    { name: 'AIAnalytics', nav: 'AI Analytics', heading: 'AI Analytics',     selector: 'text=Ask' },
    { name: 'Insights',     nav: 'Insights',      heading: 'Insights',         selector: 'text=Insight' },
    { name: 'Predictive',  nav: 'Predictive',    heading: 'Predictive',        selector: 'text=Predictive' },
    { name: 'Prescription',nav: 'Prescription',  heading: 'Prescription',      selector: 'text=Prescription' },
    { name: 'Hypothesis',  nav: 'Hypothesis',    heading: 'Hypothesis',       selector: 'text=Hypothesis' },
    { name: 'Data',        nav: 'Data',           heading: 'Data',             selector: 'text=Connect' },
    { name: 'Documents',   nav: 'Documents',     heading: 'Documents',        selector: 'text=Documents' },
    { name: 'Copilot',     nav: 'Copilot',       heading: 'Copilot',          selector: 'textarea, input[type="text"]' },
    { name: 'History',     nav: 'History',       heading: 'History',          selector: 'text=History' },
    { name: 'Settings',    nav: 'Settings',      heading: 'Settings',         selector: '.nav-item' },
  ]) {
    test(`${name} page loads`, async ({ page }) => {
      await seedAuth(page);
      await page.reload();
      await page.waitForLoadState('networkidle');
      // Navigate to page via sidebar
      await page.getByRole('button', { name: new RegExp(nav, 'i') }).click();
      await page.waitForTimeout(500);
      // Check page heading or key element exists
      const el = page.locator(`h1, h2`).filter({ hasText: new RegExp(heading, 'i') }).first();
      await expect(el).toBeVisible({ timeout: 5000 });
      // No console errors
      const errors = [];
      page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
      await page.waitForTimeout(500);
      const realErrors = errors.filter(e => !e.includes('favicon') && !e.includes('404'));
      expect(realErrors).toHaveLength(0);
    });
  }
});
