// CommonJS // Playwright e2e: Main App pages (Dashboard, Data, Schema, Analytics, etc.)
// Requires user to be authenticated.
const { test, expect } = require('@playwright/test');

const BASE = 'http://localhost:5174';

async function seedAuth(page) {
  await page.goto(BASE);
  await page.evaluate(() => {
    localStorage.setItem('aria_auth_token', 'test_token_playwright_2024');
    localStorage.setItem('aria_auth_user', JSON.stringify({ email: 'test@aria.ai', username: 'TestUser' }));
    localStorage.setItem('aria_llm_mode', 'local');
    localStorage.setItem('aria_db_configured', 'true');
  });
}

test.describe('Main App pages', () => {
  test('Dashboard loads with KPI cards and question input', async ({ page }) => {
    await seedAuth(page);
    await page.reload();
    await page.waitForLoadState('networkidle');
    // Dashboard should show KPI area or question input
    const hasInput = await page.locator('textarea, input[type="text"]').count();
    const hasHeading = await page.locator('h1, h2').count();
    expect(hasInput + hasHeading).toBeGreaterThan(0);
  });

  test('Data source page loads with connect form', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/dataSource`);
    await page.waitForLoadState('networkidle');
    const hasConnect = await page.locator('button', { hasText: /connect|submit/i }).count();
    const hasForm = await page.locator('input, select').count();
    expect(hasForm + hasConnect).toBeGreaterThan(0);
  });

  test('Schema page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/schema`);
    await page.waitForLoadState('networkidle');
    const hasSchema = await page.locator('h1, h2').count();
    expect(hasSchema).toBeGreaterThan(0);
  });

  test('Analytics page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/analytics`);
    await page.waitForLoadState('networkidle');
    const hasAnalytics = await page.locator('h1, h2').count();
    expect(hasAnalytics).toBeGreaterThan(0);
  });

  test('Insights page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/insights`);
    await page.waitForLoadState('networkidle');
    const hasInsights = await page.locator('h1, h2').count();
    expect(hasInsights).toBeGreaterThan(0);
  });

  test('Predictions page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/predictions`);
    await page.waitForLoadState('networkidle');
    const hasPredictions = await page.locator('h1, h2').count();
    expect(hasPredictions).toBeGreaterThan(0);
  });

  test('Prescriptions page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/prescriptions`);
    await page.waitForLoadState('networkidle');
    const hasPrescriptions = await page.locator('h1, h2').count();
    expect(hasPrescriptions).toBeGreaterThan(0);
  });

  test('Hypothesis page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/hypothesis`);
    await page.waitForLoadState('networkidle');
    const hasHypothesis = await page.locator('h1, h2').count();
    expect(hasHypothesis).toBeGreaterThan(0);
  });

  test('History page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/history`);
    await page.waitForLoadState('networkidle');
    const hasHistory = await page.locator('h1, h2').count();
    expect(hasHistory).toBeGreaterThan(0);
  });

  test('Documents page loads', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/documents`);
    await page.waitForLoadState('networkidle');
    const hasDocs = await page.locator('h1, h2').count();
    expect(hasDocs).toBeGreaterThan(0);
  });

  test('Settings page loads with AI config', async ({ page }) => {
    await seedAuth(page);
    await page.goto(`${BASE}#/settings`);
    await page.waitForLoadState('networkidle');
    // Check AI Configuration tab is accessible
    const hasAIConfig = await page.getByText(/AI Configuration/i).count();
    expect(hasAIConfig).toBeGreaterThan(0);
  });
});
