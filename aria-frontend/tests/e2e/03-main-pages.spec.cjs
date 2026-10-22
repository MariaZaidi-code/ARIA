// CommonJS // Playwright e2e: Main App pages (Dashboard, Data, Schema, Analytics, etc.)
// Requires user to be authenticated.
// Canonical hash contract (App.tsx VALID_PAGES): dashboard, analytics,
// insights, predictive, intelligence, data, documents, copilot, history,
// settings. #/hypothesis aliases to #/analytics where hypothesis now lives
// as embedded Possible drivers / Investigate why.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const BASE = 'http://localhost:8000';

test.describe('Main App pages', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });
  test('Dashboard loads with KPI cards and question input', async () => {
        await page.waitForLoadState('networkidle');
    // Dashboard should show KPI area or question input
    const hasInput = await page.locator('textarea, input[type="text"]').count();
    const hasHeading = await page.locator('h1, h2').count();
    expect(hasInput + hasHeading).toBeGreaterThan(0);
  });

  test('Data source page opens a database connection form', async () => {
    await page.getByRole('navigation').getByRole('button', { name: /^data$/i }).click();
    await expect(page.getByRole('heading', { name: /^data$/i })).toBeVisible();
    await page.getByRole('button', { name: /PostgreSQL Database/i }).click();
    await expect(page.getByLabel('Password')).toBeVisible();
  });

  test('Schema page loads', async () => {
        await page.goto(`${BASE}#/schema`);
    await page.waitForLoadState('networkidle');
    const hasSchema = await page.locator('h1, h2').count();
    expect(hasSchema).toBeGreaterThan(0);
  });

  test('Analytics page loads', async () => {
        await page.goto(`${BASE}#/analytics`);
    await page.waitForLoadState('networkidle');
    const hasAnalytics = await page.locator('h1, h2').count();
    expect(hasAnalytics).toBeGreaterThan(0);
  });

  test('Insights page loads', async () => {
        await page.goto(`${BASE}#/insights`);
    await page.waitForLoadState('networkidle');
    const hasInsights = await page.locator('h1, h2').count();
    expect(hasInsights).toBeGreaterThan(0);
  });

  test('Predictions page loads', async () => {
        await page.goto(`${BASE}#/predictive`);
    await page.waitForLoadState('networkidle');
    const hasPredictions = await page.locator('h1, h2').count();
    expect(hasPredictions).toBeGreaterThan(0);
  });

  test('Intelligence page loads', async () => {
        await page.goto(`${BASE}#/intelligence`);
    await page.waitForLoadState('networkidle');
    const hasIntel = await page.locator('h1, h2').count();
    expect(hasIntel).toBeGreaterThan(0);
  });

  test('legacy #/hypothesis aliases to AI Analytics (embedded Possible drivers)', async () => {
        await page.goto(`${BASE}#/hypothesis`);
    await page.waitForLoadState('networkidle');
    const heading = await page.locator('h1, h2').first().innerText().catch(() => '');
    expect(heading).toMatch(/Analytics/i);
  });

  test('History page loads', async () => {
        await page.goto(`${BASE}#/history`);
    await page.waitForLoadState('networkidle');
    const hasHistory = await page.locator('h1, h2').count();
    expect(hasHistory).toBeGreaterThan(0);
  });

  test('Documents page loads', async () => {
    const document = {
      id: 'document-preview-fixture',
      name: 'Quarterly report.pdf',
      summary: 'The report reviews quarterly revenue across the business. Revenue increased during the period, with the strongest performance in the southern region.',
      summary_version: 2,
      file_size: 2048,
      page_count: 2,
      element_count: 5,
      chunk_count: 2,
      table_count: 1,
      status: 'ready',
      created_at: '2026-10-18T12:00:00Z',
    };
    let chatAttempts = 0;
    await page.route('**/api/documents**', async (route) => {
      const url = new URL(route.request().url());
      if (url.pathname.endsWith('/overview/stats')) {
        return route.fulfill({ json: { overview: { total_documents: 1, storage_bytes: 2048 } } });
      }
      if (url.pathname.endsWith('/chunks')) {
        return route.fulfill({ json: { ok: true, chunks: [{ text: 'Quarterly revenue increased across all regions.', metadata: { page: 1 } }] } });
      }
      if (url.pathname.endsWith('/dashboard')) {
        return route.fulfill({ json: { metrics: [] } });
      }
      if (url.pathname.endsWith('/summary')) {
        return route.fulfill({ json: { ok: true, summary: document.summary, summary_version: 2 } });
      }
      return route.fulfill({ json: { documents: [document] } });
    });
    await page.route('**/api/insight/pdf/chat', async (route) => {
      chatAttempts += 1;
      if (chatAttempts === 1) {
        return route.fulfill({ status: 503, json: { detail: 'Temporary document service failure' } });
      }
      expect(route.request().postDataJSON().question).toBe('Summarize sales by region');
      return route.fulfill({
        json: {
          ok: true,
          conversation_id: 'conversation-1',
          answer: '**Sales by region** [S1]',
          sources: [{
            source_id: 'S1',
            document_id: document.id,
            filename: document.name,
            page: 1,
            content_type: 'table',
            snippet: '| Region | Sales | | --- | --- | | North | 120 | | South | 95 |',
          }],
        },
      });
    });
    await page.route('**/api/documents/document-preview-fixture', (route) => (
      route.fulfill({ json: { ok: true, document } })
    ));
    await page.goto(`${BASE}#/documents`);
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Documents' })).toBeVisible();
    await expect(page.locator('input[type="file"]')).toHaveAttribute('accept', /\.xlsx/);
    await expect(page.locator('input[type="file"]')).toHaveAttribute('accept', /\.docx/);
    await expect(page.getByRole('complementary', { name: 'Document assistant' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open Ask ARIA' })).toHaveCount(0);
    await expect(page.getByRole('dialog', { name: 'Quarterly report.pdf' })).toHaveCount(0);
    const rowActionsOverlap = await page.locator('.documents-file-row').evaluate((row) => {
      const boxes = Array.from(row.children)
        .filter((element) => getComputedStyle(element).display !== 'none')
        .map((element) => element.getBoundingClientRect())
        .filter((box) => box.width && box.height);
      return boxes.some((box, index) => index > 0 && boxes[index - 1].right > box.left + 1);
    });
    expect(rowActionsOverlap).toBe(false);
    const rowOverflowsHorizontally = await page.locator('.documents-file-row').evaluate((row) => row.scrollWidth > row.clientWidth + 1);
    expect(rowOverflowsHorizontally).toBe(false);
    await page.getByRole('button', { name: 'Preview Quarterly report.pdf' }).click();
    const preview = page.getByRole('dialog', { name: 'Quarterly report.pdf' });
    await expect(preview).toBeVisible();
    await expect(preview.getByText('Quarterly revenue increased across all regions.')).toBeVisible();
    await expect(preview.getByRole('heading', { name: 'Summary' })).toBeVisible();
    await expect(preview.getByText(document.summary)).toBeVisible();
    const previewOverflowsHorizontally = await preview.locator('.documents-preview-scroll').evaluate((element) => (
      element.scrollWidth > element.clientWidth + 1
    ));
    expect(previewOverflowsHorizontally).toBe(false);
    const dimensions = await page.locator('.documents-workspace').evaluate((element) => {
      const heading = document.querySelector('.documents-header h1');
      return {
        workspaceHeight: element.getBoundingClientRect().height,
        headingFontSize: Number.parseFloat(getComputedStyle(heading).fontSize),
        statLabelFontSize: Number.parseFloat(getComputedStyle(document.querySelector('.documents-stat small')).fontSize),
      };
    });
    expect(dimensions.workspaceHeight).toBeGreaterThanOrEqual(640);
    expect(dimensions.headingFontSize).toBeGreaterThanOrEqual(28);
    expect(dimensions.statLabelFontSize).toBeGreaterThanOrEqual(12);
    await preview.getByRole('button', { name: 'Close preview' }).click();
    await expect(preview).toHaveCount(0);
    await page.setViewportSize({ width: 700, height: 800 });
    await page.getByRole('button', { name: 'Preview Quarterly report.pdf' }).click();
    const mobilePreview = page.getByRole('dialog', { name: 'Quarterly report.pdf' });
    await expect(mobilePreview).toBeVisible();
    const mobilePreviewOverflowsHorizontally = await mobilePreview.locator('.documents-preview-scroll').evaluate((element) => (
      element.scrollWidth > element.clientWidth + 1
    ));
    expect(mobilePreviewOverflowsHorizontally).toBe(false);
    await mobilePreview.getByRole('button', { name: 'Close preview' }).click();
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.getByRole('textbox', { name: 'Ask the document assistant' }).fill('Summarize sales by region');
    await page.getByRole('button', { name: 'Send question' }).click();
    await expect(page.getByRole('button', { name: 'Try again' })).toBeVisible();
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByText('Sales by region [S1]', { exact: true })).toBeVisible();
    await expect(page.locator('.documents-answer-chart')).toBeVisible();
    await expect(page.getByRole('figure', { name: 'Chart of Sales' })).toBeVisible();
    await expect(page.locator('.documents-answer-chart-row')).toHaveCount(2);
    await expect(page.locator('.documents-chat-answer > p').last()).not.toContainText('*');
    const answerFontSize = await page.locator('.documents-chat-answer > p').last().evaluate((element) => (
      Number.parseFloat(getComputedStyle(element).fontSize)
    ));
    expect(answerFontSize).toBeGreaterThanOrEqual(14);
    const questionFontSize = await page.locator('.documents-chat-question').last().evaluate((element) => (
      Number.parseFloat(getComputedStyle(element).fontSize)
    ));
    expect(questionFontSize).toBeGreaterThanOrEqual(14);
    await expect(page.getByRole('button', { name: '[S1] Quarterly report.pdf · p. 1' })).toBeVisible();
  });

  test('Settings page loads with AI config', async () => {
        await page.goto(`${BASE}#/settings`);
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: /^settings$/i })).toBeVisible();
    await expect(page.getByRole('button', { name: /AI Configuration/i })).toBeVisible();
  });
});
