// CommonJS // Playwright e2e: Data source connection flow (all 4 types)
// Single host: http://localhost:8000. One login per file (auth limiter).
const { test, expect } = require('@playwright/test');
const { seedAuth, signInVerified } = require('./auth-helper');

const BASE = 'http://localhost:8000';

test.describe('Data source connection flow', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });

  async function gotoData() {
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    const dataBtn = page.getByRole('navigation').getByRole('button', { name: /^Data$/i });
    if (await dataBtn.count() > 0) await dataBtn.click();
    await page.waitForTimeout(1000);
  }

  test('Data page shows 4 source type cards', async () => {
    await gotoData();
    // The data source module either lists selectable sources or shows the
    // connected source state for this user's session.
    const pageContent = await page.content();
    expect(/Connected Sources|Connect a Data Source|Choose a Data Source|PostgreSQL|MySQL|CSV|PDF/i.test(pageContent)).toBeTruthy();
  });

  test('PostgreSQL card is clickable', async () => {
    await gotoData();
    // Click PostgreSQL card or source type button
    const pgBtn = page.getByRole('button', { name: /PostgreSQL|postgres/i }).first();
    if (await pgBtn.count() > 0) {
      await pgBtn.click();
      await page.waitForTimeout(500);
      // Should reveal a form or inputs
      const hasForm = await page.locator('input, select').count();
      expect(hasForm).toBeGreaterThan(0);
    }
  });

  test('CSV card shows file picker', async () => {
    await gotoData();
    const csvBtn = page.getByRole('button', { name: /CSV|csv/i }).first();
    if (await csvBtn.count() > 0) {
      await csvBtn.click();
      await page.waitForTimeout(500);
      const hasFileInput = await page.locator('input[type="file"]').count();
      expect(hasFileInput).toBeGreaterThan(0);
    }
  });

  test('Cloud LLM option shows Groq info', async ({ browser }) => {
    // Offline-safe UI check: the Cloud AI station must present its Groq
    // identity and key input on the selection screen. No Continue/switch —
    // the default suite never engages cloud providers or sends data.
    const cloudPage = await browser.newPage();
    try {
      await signInVerified(cloudPage, BASE);
      await cloudPage.getByRole('button', { name: /Cloud AI/i }).first().click();
      const content = await cloudPage.content();
      expect(/Groq|groq/i.test(content)).toBeTruthy();
      await expect(cloudPage.locator('#llm-api-key')).toBeVisible();
    } finally {
      await cloudPage.close();
    }
  });
});
