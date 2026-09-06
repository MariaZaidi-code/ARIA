# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 04-data-connect.spec.cjs >> Data source connection flow >> Cloud LLM selection shows Groq info
- Location: tests\e2e\04-data-connect.spec.cjs:68:3

# Error details

```
Error: expect(received).toBeTruthy()

Received: false
```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - complementary [ref=f1e4]:
    - generic [ref=f1e10]:
      - generic [ref=f1e11]: ARIA
      - generic [ref=f1e12]: AI
    - navigation [ref=f1e13]:
      - button "Dashboard" [ref=f1e14]
      - button "AI Analytics" [ref=f1e21]
      - button "Insights" [ref=f1e26]
      - button "Predictive" [ref=f1e30]
      - button "Prescription" [ref=f1e35]
      - button "Hypothesis" [ref=f1e41]
      - button "Data" [ref=f1e45]
      - button "Documents" [ref=f1e51]
      - button "Copilot" [ref=f1e57]
      - button "History" [ref=f1e62]
      - button "Settings" [ref=f1e67]
    - generic [ref=f1e73]:
      - generic [ref=f1e74]: A
      - generic [ref=f1e75]:
        - paragraph [ref=f1e76]: User
        - paragraph [ref=f1e77]: user@email.com
    - button [ref=f1e78]
  - generic [ref=f1e81]:
    - banner [ref=f1e82]:
      - heading "Dashboard" [level=1] [ref=f1e84]
      - button "Search... ⌘K" [ref=f1e85]:
        - generic [ref=f1e89]: Search...
        - generic [ref=f1e90]: ⌘K
      - button "Toggle theme" [ref=f1e91]
      - button "Notifications" [ref=f1e94]
      - button "A" [ref=f1e100]
    - main [ref=f1e104]:
      - generic [ref=f1e107]:
        - heading "Connect a Data Source" [level=2] [ref=f1e112]
        - paragraph [ref=f1e113]: Get started by connecting your database or uploading a file to unlock AI-powered insights.
        - button "Connect Now" [ref=f1e114]
```

# Test source

```ts
  1  | // CommonJS // Playwright e2e: Data source connection flow (all 4 types)
  2  | const { test, expect } = require('@playwright/test');
  3  | 
  4  | const BASE = 'http://localhost:5174';
  5  | 
  6  | async function seedAuth(page, llmMode = 'local') {
  7  |   await page.goto(BASE);
  8  |   await page.evaluate((mode) => {
  9  |     localStorage.setItem('aria_auth_token', 'test_token_playwright_2024');
  10 |     localStorage.setItem('aria_auth_user', JSON.stringify({ email: 'test@aria.ai', username: 'TestUser' }));
  11 |     localStorage.setItem('aria_llm_mode', mode);
  12 |     localStorage.setItem('aria_db_configured', 'false');
  13 |   }, llmMode);
  14 | }
  15 | 
  16 | test.describe('Data source connection flow', () => {
  17 |   test('Data page shows 4 source type cards', async ({ page }) => {
  18 |     await seedAuth(page);
  19 |     await page.goto(BASE);
  20 |     await page.waitForLoadState('networkidle');
  21 |     // Navigate to Data page
  22 |     const dataBtn = page.getByRole('button', { name: /Data/i }).first();
  23 |     if (await dataBtn.count() > 0) await dataBtn.click();
  24 |     await page.waitForTimeout(1000);
  25 |     // Should show cards for PostgreSQL, MySQL, CSV, PDF
  26 |     const pageContent = await page.content();
  27 |     const hasPostgres = /PostgreSQL|postgresql|postgres/i.test(pageContent);
  28 |     const hasMySQL = /MySQL|mysql/i.test(pageContent);
  29 |     const hasCSV = /CSV|csv/i.test(pageContent);
  30 |     const hasPDF = /PDF|pdf/i.test(pageContent);
  31 |     expect(hasPostgres || hasMySQL || hasCSV || hasPDF).toBeTruthy();
  32 |   });
  33 | 
  34 |   test('PostgreSQL card is clickable', async ({ page }) => {
  35 |     await seedAuth(page);
  36 |     await page.goto(BASE);
  37 |     await page.waitForLoadState('networkidle');
  38 |     const dataBtn = page.getByRole('button', { name: /Data/i }).first();
  39 |     if (await dataBtn.count() > 0) await dataBtn.click();
  40 |     await page.waitForTimeout(1000);
  41 |     // Click PostgreSQL card or source type button
  42 |     const pgBtn = page.getByRole('button', { name: /PostgreSQL|postgres/i }).first();
  43 |     if (await pgBtn.count() > 0) {
  44 |       await pgBtn.click();
  45 |       await page.waitForTimeout(500);
  46 |       // Should reveal a form or inputs
  47 |       const hasForm = await page.locator('input, select').count();
  48 |       expect(hasForm).toBeGreaterThan(0);
  49 |     }
  50 |   });
  51 | 
  52 |   test('CSV card shows file picker', async ({ page }) => {
  53 |     await seedAuth(page);
  54 |     await page.goto(BASE);
  55 |     await page.waitForLoadState('networkidle');
  56 |     const dataBtn = page.getByRole('button', { name: /Data/i }).first();
  57 |     if (await dataBtn.count() > 0) await dataBtn.click();
  58 |     await page.waitForTimeout(1000);
  59 |     const csvBtn = page.getByRole('button', { name: /CSV|csv/i }).first();
  60 |     if (await csvBtn.count() > 0) {
  61 |       await csvBtn.click();
  62 |       await page.waitForTimeout(500);
  63 |       const hasFileInput = await page.locator('input[type="file"]').count();
  64 |       expect(hasFileInput).toBeGreaterThan(0);
  65 |     }
  66 |   });
  67 | 
  68 |   test('Cloud LLM selection shows Groq info', async ({ page }) => {
  69 |     await seedAuth(page, 'cloud');
  70 |     await page.goto(BASE);
  71 |     await page.waitForLoadState('networkidle');
  72 |     // Dashboard or AppShell should show "Cloud" indicator
  73 |     const content = await page.content();
  74 |     const hasCloud = /Cloud|cloud|Groq|groq/i.test(content);
> 75 |     expect(hasCloud).toBeTruthy();
     |                      ^ Error: expect(received).toBeTruthy()
  76 |   });
  77 | });
  78 | 
```