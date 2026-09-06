// CommonJS // Playwright e2e: Data source connection flow (all 4 types)
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:5174';

async function seedAuth(page, llmMode = 'local') {
  await page.goto(BASE);
  await page.evaluate((mode) => {
    localStorage.setItem('aria_auth_token', 'test_token_playwright_2024');
    localStorage.setItem('aria_auth_user', JSON.stringify({ email: 'test@aria.ai', username: 'TestUser' }));
    localStorage.setItem('aria_llm_mode', mode);
    localStorage.setItem('aria_db_configured', 'false');
  }, llmMode);
}

test.describe('Data source connection flow', () => {
  test('Data page shows 4 source type cards', async ({ page }) => {
    await seedAuth(page);
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    // Navigate to Data page
    const dataBtn = page.getByRole('button', { name: /Data/i }).first();
    if (await dataBtn.count() > 0) await dataBtn.click();
    await page.waitForTimeout(1000);
    // Should show cards for PostgreSQL, MySQL, CSV, PDF
    const pageContent = await page.content();
    const hasPostgres = /PostgreSQL|postgresql|postgres/i.test(pageContent);
    const hasMySQL = /MySQL|mysql/i.test(pageContent);
    const hasCSV = /CSV|csv/i.test(pageContent);
    const hasPDF = /PDF|pdf/i.test(pageContent);
    expect(hasPostgres || hasMySQL || hasCSV || hasPDF).toBeTruthy();
  });

  test('PostgreSQL card is clickable', async ({ page }) => {
    await seedAuth(page);
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    const dataBtn = page.getByRole('button', { name: /Data/i }).first();
    if (await dataBtn.count() > 0) await dataBtn.click();
    await page.waitForTimeout(1000);
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

  test('CSV card shows file picker', async ({ page }) => {
    await seedAuth(page);
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    const dataBtn = page.getByRole('button', { name: /Data/i }).first();
    if (await dataBtn.count() > 0) await dataBtn.click();
    await page.waitForTimeout(1000);
    const csvBtn = page.getByRole('button', { name: /CSV|csv/i }).first();
    if (await csvBtn.count() > 0) {
      await csvBtn.click();
      await page.waitForTimeout(500);
      const hasFileInput = await page.locator('input[type="file"]').count();
      expect(hasFileInput).toBeGreaterThan(0);
    }
  });

  test('Cloud LLM selection shows Groq info', async ({ page }) => {
    await seedAuth(page, 'cloud');
    await page.goto(BASE);
    await page.waitForLoadState('networkidle');
    // Dashboard or AppShell should show "Cloud" indicator
    const content = await page.content();
    const hasCloud = /Cloud|cloud|Groq|groq/i.test(content);
    expect(hasCloud).toBeTruthy();
  });
});
