// Real cookie-authenticated CSV upload and navigation with no hosted API key.
// Inference is tested separately by credential-gated LLM suites.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');
const BASE = process.env.ARIA_BASE || 'http://localhost:8000';
const CSV = [
  'order_id,product_category,sales,quantity',
  '1,Home,120,2',
  '2,Electronics,280,1',
  '3,Home,75,1',
  '4,Grocery,42,5',
  '5,Electronics,160,1',
  '6,Home,95,3',
].join('\n') + '\n';

test('Real CSV ingestion survives navigation across ARIA analytics pages', async ({ page }) => {
  const { username } = await seedAuth(page, BASE);
  const upload = await page.request.post(BASE + '/api/connect_file', {
    multipart: {
      provider: 'local',
      file: { name: 'e2e_retail.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV, 'utf8') },
    },
    timeout: 120000,
  });
  expect(upload.ok(), 'CSV upload must succeed: ' + (await upload.text()).slice(0, 250)).toBeTruthy();
  const data = await upload.json();
  expect(data.ok).toBe(true);
  expect(Number(data.rows)).toBeGreaterThan(0);
  const status = await page.request.get(BASE + '/api/session/status');
  expect(status.ok(), 'Session must remain authenticated after CSV connect').toBeTruthy();
  const session = await status.json();
  expect(session.connection_status).toBe('connected');

  for (const { label, id } of [
    { label: 'Data', id: 'data' },
    { label: 'AI Analytics', id: 'analytics' },
    { label: 'Insights', id: 'insights' },
    { label: 'Forecast', id: 'predictive' },
    { label: 'Intelligence', id: 'intelligence' },
    { label: 'Copilot', id: 'copilot' },
    { label: 'History', id: 'history' },
  ]) {
    await page.locator('nav').getByRole('button', { name: label, exact: true }).click();
    await expect(page).toHaveURL(new RegExp('#/' + id + '$'));
    await expect(page.locator('header h1')).toContainText(label);
    await expect(page.locator('main')).not.toBeEmpty({ timeout: 15000 });
  }
  expect(username).toMatch(/_at_aria\.test$/);
});
