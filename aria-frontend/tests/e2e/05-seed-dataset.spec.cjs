// Seeds the E2E user's session with a real connected CSV before the
// data-dependent specs run (intelligence, full journey, QA). Specs that need
// the clean "connect a source" state (03/04) run earlier by filename order.
const { test, expect, request } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const BASE = 'http://localhost:8000';
const CSV = process.env.ARIA_CSV ||
  'C:\\Users\\Go\\Desktop\\ARIA\\data\\kaggle_retail_sales\\abbas829__ecommerce-sales-dataset\\ecommerce_sales_analytics_5000.csv';

test.describe('Seed connected dataset', () => {
  test('connect ecommerce CSV for downstream specs', async () => {
    test.skip(!fs.existsSync(CSV), `CSV fixture missing: ${CSV}`);
    test.setTimeout(300000);
    const ctx = await request.newContext({
      baseURL: BASE,
      extraHTTPHeaders: { Origin: BASE, Referer: `${BASE}/` },
    });
    try {
      const login = await ctx.post('/api/auth/login', {
        data: {
          email: process.env.ARIA_E2E_EMAIL,
          password: process.env.ARIA_E2E_PASSWORD,
        },
      });
      expect(login.ok(), `login failed: ${login.status()}`).toBeTruthy();
      const res = await ctx.post('/api/connect_file', {
        multipart: {
          file: {
            name: path.basename(CSV),
            mimeType: 'text/csv',
            buffer: fs.readFileSync(CSV),
          },
        },
      });
      const body = await res.json().catch(() => ({}));
      expect(res.ok(), `connect_file failed: ${JSON.stringify(body)}`).toBeTruthy();
      expect(body.ok).toBeTruthy();
      expect(body.rows).toBeGreaterThan(0);
    } finally {
      await ctx.dispose();
    }
  });
});
