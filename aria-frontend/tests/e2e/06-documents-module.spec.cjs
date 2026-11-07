// CommonJS // Playwright e2e: Document Module — multi-file upload progress,
// chat sessions, charts, confirm dialogs, loading/error/empty states,
// dark mode and phone width. Every document API is mocked with synthetic
// data so the spec needs no PostgreSQL, pgvector or AI provider.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const BASE = process.env.ARIA_E2E_BASE_URL || 'http://localhost:8000';

const READY_DOC = {
  id: 'doc-alpha-0001',
  name: 'Regional sales 2025.pdf',
  summary: 'Synthetic regional sales report.',
  summary_version: 3,
  file_size: 4096,
  page_count: 3,
  element_count: 12,
  chunk_count: 4,
  table_count: 1,
  status: 'ready',
  created_at: '2026-10-20T09:00:00Z',
};

/** Install mocks; `state` is mutated by tests to drive scenarios. */
async function mockDocumentApis(page, state) {
  await page.route('**/api/documents**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.endsWith('/overview/stats')) {
      return route.fulfill({ json: { ok: true, overview: { total_documents: state.documents.length, storage_bytes: 4096 } } });
    }
    if (path.endsWith('/upload-jobs')) {
      state.jobPolls += 1;
      return route.fulfill({ json: { ok: true, jobs: state.jobsFor(state.jobPolls) } });
    }
    if (path.endsWith('/chunks')) return route.fulfill({ json: { ok: true, chunks: [] } });
    if (path.endsWith('/dashboard')) return route.fulfill({ json: { metrics: [] } });
    if (request.method() === 'DELETE') {
      state.deletedDocuments.push(path.split('/').pop());
      state.documents = state.documents.filter((doc) => !path.endsWith(doc.id));
      return route.fulfill({ json: { ok: true } });
    }
    if (path === '/api/documents') {
      if (state.listFails) return route.fulfill({ status: 500, json: { detail: 'Document service unavailable' } });
      if (state.listDelayMs) await new Promise((resolve) => setTimeout(resolve, state.listDelayMs));
      return route.fulfill({ json: { ok: true, documents: state.documents } });
    }
    return route.fulfill({ json: { ok: true, document: state.documents[0] || READY_DOC } });
  });
  await page.route('**/api/insight/pdf/upload-batch', async (route) => {
    state.uploadedBodies.push(route.request().postDataBuffer()?.length || 0);
    return route.fulfill({
      status: 202,
      json: {
        ok: true,
        batch_id: 'batch-1',
        jobs: [
          { job_id: 'job-a', batch_id: 'batch-1', filename: 'q3-report.pdf', status: 'queued', stage: 'queued', progress: 0 },
          { job_id: 'job-b', batch_id: 'batch-1', filename: 'budget.csv', status: 'queued', stage: 'queued', progress: 0 },
        ],
      },
    });
  });
  await page.route('**/api/insight/pdf/conversations**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === 'DELETE') {
      state.deletedChats.push(url.pathname.split('/').pop());
      state.chats = [];
      return route.fulfill({ json: { ok: true } });
    }
    if (url.pathname.endsWith('/conversations')) {
      return route.fulfill({ json: { ok: true, conversations: state.chats } });
    }
    return route.fulfill({
      json: {
        ok: true,
        conversation: {
          conversation_id: 'conversation-0001',
          title: 'Revenue by region',
          scope_document_ids: [READY_DOC.id],
          messages: [
            { role: 'user', content: 'What was revenue by region?' },
            {
              role: 'assistant',
              content: '- North: 120 [S1]\n-\n- South: 95 [S1]',
              sources: [{ source_id: 'S1', document_id: READY_DOC.id, filename: READY_DOC.name, page: 2, location_label: 'p. 2, table 1' }],
            },
          ],
        },
      },
    });
  });
  await page.route('**/api/insight/pdf/chat', async (route) => {
    state.chatBodies.push(route.request().postDataJSON());
    return route.fulfill({
      json: {
        ok: true,
        conversation_id: 'conversation-0002',
        answer: 'Revenue grew in both years [S1] [S2].',
        sources: [
          { source_id: 'S1', document_id: READY_DOC.id, filename: 'report-2024.pdf', page: 1, location_label: 'p. 1, table 1' },
          { source_id: 'S2', document_id: READY_DOC.id, filename: 'report-2025.pdf', page: 4, location_label: 'p. 4, table 1' },
        ],
        visualization: {
          type: 'bar',
          title: 'Revenue by Region across documents',
          x_key: 'label',
          series: [
            { key: 'report-2024.pdf', label: 'report-2024.pdf', source_id: 'S1' },
            { key: 'report-2025.pdf', label: 'report-2025.pdf', source_id: 'S2' },
          ],
          data: [
            { label: 'North', 'report-2024.pdf': 10, 'report-2025.pdf': 15 },
            { label: 'South', 'report-2024.pdf': 20, 'report-2025.pdf': 25 },
          ],
          cross_document: true,
          source_ids: ['S1', 'S2'],
        },
      },
    });
  });
}

/** A same-hash goto does not remount the page; reload so mocks apply on mount. */
async function openDocuments(page) {
  await page.goto(`${BASE}#/documents`);
  await page.reload();
}

function freshState(overrides = {}) {
  return {
    documents: [READY_DOC],
    chats: [],
    jobPolls: 0,
    uploadedBodies: [],
    chatBodies: [],
    deletedChats: [],
    deletedDocuments: [],
    listFails: false,
    listDelayMs: 0,
    jobsFor: () => [],
    ...overrides,
  };
}

test.describe('Document Module', () => {
  let page;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await seedAuth(page, BASE);
  });
  test.afterAll(async () => { await page.close(); });
  test.afterEach(async () => {
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await page.evaluate(() => document.documentElement.classList.remove('dark'));
    await page.setViewportSize({ width: 1280, height: 800 });
  });

  test('multi-file upload shows per-file progress, failures and retry', async () => {
    const state = freshState({
      documents: [],
      jobsFor: (poll) => (poll === 1
        ? [
          { job_id: 'job-a', status: 'processing', stage: 'indexing', progress: 70 },
          { job_id: 'job-b', status: 'processing', stage: 'extracting', progress: 35 },
        ]
        : [
          { job_id: 'job-a', status: 'ready', stage: 'ready', progress: 100, document: { document_id: READY_DOC.id } },
          { job_id: 'job-b', status: 'failed', stage: 'failed', progress: 100, error: 'The uploaded workbook could not be read.' },
        ]),
    });
    await mockDocumentApis(page, state);
    await openDocuments(page);
    await expect(page.getByText('No documents yet')).toBeVisible();

    const input = page.locator('input[type="file"]');
    await expect(input).toHaveAttribute('multiple', '');
    state.documents = [];
    await input.setInputFiles([
      { name: 'q3-report.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 synthetic report') },
      { name: 'budget.csv', mimeType: 'text/csv', buffer: Buffer.from('month,amount\nJan,10\n') },
      { name: 'notes.txt', mimeType: 'text/plain', buffer: Buffer.from('not supported') },
    ]);

    const queue = page.getByRole('region', { name: 'Upload progress' });
    await expect(queue.getByTestId('upload-item')).toHaveCount(3);
    // Rejected in the browser before upload; never sent to the server.
    await expect(queue.getByText('Use a PDF, CSV, XLSX, or DOCX file.')).toBeVisible();
    state.documents = [READY_DOC];
    await expect(queue.getByText('Ready', { exact: true })).toBeVisible({ timeout: 15000 });
    await expect(queue.getByRole('progressbar', { name: 'q3-report.pdf upload progress' })).toHaveAttribute('aria-valuenow', '100');
    await expect(queue.getByText('The uploaded workbook could not be read.')).toBeVisible();
    await expect(queue.getByRole('button', { name: 'Retry budget.csv' })).toBeVisible();
    await expect(queue.getByRole('button', { name: 'Retry notes.txt' })).toHaveCount(0);
    expect(state.uploadedBodies).toHaveLength(1);
    expect(state.jobPolls).toBeGreaterThanOrEqual(2);
    await page.keyboard.press('Escape'); // close the auto-opened preview of the single ready file
    await queue.getByRole('button', { name: 'Clear finished' }).click();
    await expect(queue).toHaveCount(0);
  });

  test('saved chats reopen with their document scope and clean answers', async () => {
    const state = freshState({
      chats: [{ conversation_id: 'conversation-0001', title: 'Revenue by region', updated_at: '2026-10-25T10:00:00Z', message_count: 2, scope_document_ids: [READY_DOC.id] }],
    });
    await mockDocumentApis(page, state);
    await openDocuments(page);
    await page.getByRole('button', { name: /Chats \(1\)/ }).click();
    await page.getByRole('button', { name: /^Revenue by region/ }).click();

    const assistant = page.getByRole('complementary', { name: 'Document assistant' });
    await expect(assistant.getByText('What was revenue by region?')).toBeVisible();
    const items = assistant.locator('.doc-answer-markdown li');
    await expect(items).toHaveCount(2); // the empty "-" bullet is dropped
    await expect(items.first()).toHaveText('North: 120 [S1]');
    await expect(assistant.getByRole('button', { name: '[S1] Regional sales 2025.pdf · p. 2, table 1' })).toBeVisible();
    await expect(assistant.getByText('Answers scoped to 1 selected document')).toBeVisible();

    await assistant.getByRole('button', { name: 'New chat' }).click();
    await expect(assistant.getByText('Ask questions about your documents')).toBeVisible();
  });

  test('cross-document answer renders a chart and sends an explicit scope', async () => {
    const state = freshState();
    await mockDocumentApis(page, state);
    await openDocuments(page);
    await page.getByRole('textbox', { name: 'Ask the document assistant' }).fill('Compare revenue by region');
    await page.getByRole('button', { name: 'Send question' }).click();
    const chart = page.getByRole('figure', { name: 'Chart: Revenue by Region across documents' });
    await expect(chart).toBeVisible();
    await expect(chart.getByText('Compared across cited documents')).toBeVisible();
    await expect(chart.locator('.recharts-surface').first()).toBeVisible();
    await expect(chart.getByRole('button', { name: 'View cited data [S2]' })).toBeVisible();
    // No selection means "all documents", sent explicitly as [].
    expect(state.chatBodies[0].document_ids).toEqual([]);
    await expect(page.getByRole('button', { name: '[S2] report-2025.pdf · p. 4, table 1' })).toBeVisible();
  });

  test('deletes use an accessible confirmation dialog', async () => {
    const state = freshState({
      chats: [{ conversation_id: 'conversation-0001', title: 'Revenue by region', message_count: 2 }],
    });
    await mockDocumentApis(page, state);
    let nativeDialog = false;
    page.once('dialog', async (dialog) => { nativeDialog = true; await dialog.dismiss(); });
    await openDocuments(page);

    await page.getByRole('button', { name: `More actions for ${READY_DOC.name}` }).click();
    await page.getByRole('button', { name: 'Delete' }).last().click();
    const confirm = page.getByRole('alertdialog', { name: 'Delete this document?' });
    await expect(confirm).toBeVisible();
    await confirm.getByRole('button', { name: 'Cancel' }).click();
    await expect(confirm).toHaveCount(0);
    expect(state.deletedDocuments).toEqual([]);

    await page.getByRole('button', { name: /Chats \(1\)/ }).click();
    await page.getByRole('button', { name: 'Delete chat Revenue by region' }).click();
    await page.getByRole('alertdialog', { name: 'Delete this chat?' }).getByRole('button', { name: 'Delete' }).click();
    await expect.poll(() => state.deletedChats).toEqual(['conversation-0001']);
    expect(nativeDialog).toBe(false);
  });

  test('loading skeleton, error and retry states', async () => {
    const state = freshState({ listDelayMs: 1500 });
    await mockDocumentApis(page, state);
    await openDocuments(page);
    await expect(page.getByLabel('Loading documents')).toBeVisible();
    await expect(page.getByText(READY_DOC.name)).toBeVisible();

    state.listFails = true;
    state.listDelayMs = 0;
    await page.reload();
    await expect(page.getByText("Documents couldn't be loaded")).toBeVisible();
    state.listFails = false;
    await page.getByRole('button', { name: 'Try again' }).click();
    await expect(page.getByText(READY_DOC.name)).toBeVisible();
  });

  test('new components follow dark mode and fit a phone screen', async () => {
    const state = freshState({
      jobsFor: () => [{ job_id: 'job-a', status: 'processing', stage: 'indexing', progress: 70 }],
    });
    await mockDocumentApis(page, state);
    await openDocuments(page);
    await page.locator('input[type="file"]').setInputFiles([
      { name: 'q3-report.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4 synthetic') },
    ]);
    const queue = page.getByRole('region', { name: 'Upload progress' });
    await expect(queue).toBeVisible();
    const light = await queue.evaluate((element) => getComputedStyle(element).backgroundColor);
    await page.evaluate(() => document.documentElement.classList.add('dark'));
    const dark = await queue.evaluate((element) => getComputedStyle(element).backgroundColor);
    expect(dark).not.toBe(light);
    expect(dark).toBe('rgb(24, 24, 27)'); // --card in the dark theme

    await page.setViewportSize({ width: 390, height: 844 });
    const overflow = await page.locator('.documents-page').evaluate((element) => element.scrollWidth - element.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    await expect(queue).toBeVisible();
  });
});
