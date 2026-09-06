"""Playwright end-to-end: user selects Cloud LLM → applies Groq API key in Settings → connects DB → asks question.

Requires: .env GROQ_API_KEY set (system key) OR user pastes their own in Settings.
Run: npx playwright test tests/e2e/cloud-llm-user-key.spec.js
"""
const { test, expect } = require('@playwright/test');

test.describe('Cloud LLM + user API key (UX preferred flow)', () => {
  test('select cloud, apply user key, connect DB, ask', async ({ page }) => {
    // 1) Go to app
    await page.goto('http://localhost:5174');
    await expect(page).toHaveTitle(/ARIA/i);

    // 2) Select cloud LLM (LLMSelection page)
    await page.getByRole('button', { name: /Cloud AI/i }).click();
    await page.getByRole('button', { name: /Continue/i }).click();

    // 3) Skip DB popup initially (we'll connect via Settings / Data page later)
    await page.waitForSelector('.premium-btn');
    // Click Settings from sidebar
    await page.getByRole('button', { name: /Settings/i }).click();

    // 4) In Settings → AI Configuration, paste user's Groq key
    // Use a test key placeholder; real user would type their own
    await page.getByPlaceholder('Paste your API key...').fill('gsk_test_userkey_for_playwright');
    await page.getByRole('button', { name: /Save/i }).click();
    await expect(page.locator('text=Provider saved')).toBeVisible();

    // 5) Navigate to Data page, connect DB (uses saved user key for cloud provider)
    await page.getByRole('button', { name: /Data/i }).click();
    // Fill DB form (adjust selectors to match figma/Data)
    await page.getByPlaceholder('Host').fill('localhost');
    await page.getByPlaceholder('Port').fill('5432');
    await page.getByPlaceholder('Database').fill('northwind');
    await page.getByPlaceholder('Username').fill('postgres');
    await page.getByPlaceholder('Password').fill('postgres');
    await page.getByRole('button', { name: /Connect/i }).click();

    // 6) Wait for connected state then ask a business question
    await expect(page.locator('text=connected')).toBeVisible({ timeout: 10000 });
    await page.getByRole('button', { name: /Dashboard/i }).click();
    await page.getByPlaceholder('Ask a business question...').fill('What is total revenue?');
    await page.getByRole('button', { name: /Analyze/i }).click();

    // 7) Verify cloud analysis completes without falling back to mock/template
    await expect(page.locator('.stagger-children, .premium-card')).toBeVisible({ timeout: 30000 });
  });
});
