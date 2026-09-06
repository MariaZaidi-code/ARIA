# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 03-main-pages.spec.cjs >> Main App pages >> Settings page loads with AI config
- Location: tests\e2e\03-main-pages.spec.cjs:101:3

# Error details

```
Error: expect(received).toBeGreaterThan(expected)

Expected: > 0
Received:   0
```

# Page snapshot

```yaml
- generic [ref=e3]:
  - complementary [ref=e4]:
    - generic [ref=e10]:
      - generic [ref=e11]: ARIA
      - generic [ref=e12]: AI
    - navigation [ref=e13]:
      - button "Dashboard" [ref=e14]
      - button "AI Analytics" [ref=e21]
      - button "Insights" [ref=e26]
      - button "Predictive" [ref=e30]
      - button "Prescription" [ref=e35]
      - button "Hypothesis" [ref=e41]
      - button "Data" [ref=e45]
      - button "Documents" [ref=e51]
      - button "Copilot" [ref=e57]
      - button "History" [ref=e62]
      - button "Settings" [ref=e67]
    - generic [ref=e73]:
      - generic [ref=e74]: A
      - generic [ref=e75]:
        - paragraph [ref=e76]: User
        - paragraph [ref=e77]: user@email.com
    - button [ref=e78]
  - generic [ref=e81]:
    - banner [ref=e82]:
      - heading "Dashboard" [level=1] [ref=e84]
      - button "Search... ⌘K" [ref=e85]:
        - generic [ref=e89]: Search...
        - generic [ref=e90]: ⌘K
      - button "Toggle theme" [ref=e91]
      - button "Notifications" [ref=e94]
      - button "A" [ref=e100]
    - main [ref=e104]:
      - generic [ref=e107]:
        - heading "Connect a Data Source" [level=2] [ref=e112]
        - paragraph [ref=e113]: Get started by connecting your database or uploading a file to unlock AI-powered insights.
        - button "Connect Now" [ref=e114]
```

# Test source

```ts
  7   | async function seedAuth(page) {
  8   |   await page.goto(BASE);
  9   |   await page.evaluate(() => {
  10  |     localStorage.setItem('aria_auth_token', 'test_token_playwright_2024');
  11  |     localStorage.setItem('aria_auth_user', JSON.stringify({ email: 'test@aria.ai', username: 'TestUser' }));
  12  |     localStorage.setItem('aria_llm_mode', 'local');
  13  |     localStorage.setItem('aria_db_configured', 'true');
  14  |   });
  15  | }
  16  | 
  17  | test.describe('Main App pages', () => {
  18  |   test('Dashboard loads with KPI cards and question input', async ({ page }) => {
  19  |     await seedAuth(page);
  20  |     await page.reload();
  21  |     await page.waitForLoadState('networkidle');
  22  |     // Dashboard should show KPI area or question input
  23  |     const hasInput = await page.locator('textarea, input[type="text"]').count();
  24  |     const hasHeading = await page.locator('h1, h2').count();
  25  |     expect(hasInput + hasHeading).toBeGreaterThan(0);
  26  |   });
  27  | 
  28  |   test('Data source page loads with connect form', async ({ page }) => {
  29  |     await seedAuth(page);
  30  |     await page.goto(`${BASE}#/dataSource`);
  31  |     await page.waitForLoadState('networkidle');
  32  |     const hasConnect = await page.locator('button', { hasText: /connect|submit/i }).count();
  33  |     const hasForm = await page.locator('input, select').count();
  34  |     expect(hasForm + hasConnect).toBeGreaterThan(0);
  35  |   });
  36  | 
  37  |   test('Schema page loads', async ({ page }) => {
  38  |     await seedAuth(page);
  39  |     await page.goto(`${BASE}#/schema`);
  40  |     await page.waitForLoadState('networkidle');
  41  |     const hasSchema = await page.locator('h1, h2').count();
  42  |     expect(hasSchema).toBeGreaterThan(0);
  43  |   });
  44  | 
  45  |   test('Analytics page loads', async ({ page }) => {
  46  |     await seedAuth(page);
  47  |     await page.goto(`${BASE}#/analytics`);
  48  |     await page.waitForLoadState('networkidle');
  49  |     const hasAnalytics = await page.locator('h1, h2').count();
  50  |     expect(hasAnalytics).toBeGreaterThan(0);
  51  |   });
  52  | 
  53  |   test('Insights page loads', async ({ page }) => {
  54  |     await seedAuth(page);
  55  |     await page.goto(`${BASE}#/insights`);
  56  |     await page.waitForLoadState('networkidle');
  57  |     const hasInsights = await page.locator('h1, h2').count();
  58  |     expect(hasInsights).toBeGreaterThan(0);
  59  |   });
  60  | 
  61  |   test('Predictions page loads', async ({ page }) => {
  62  |     await seedAuth(page);
  63  |     await page.goto(`${BASE}#/predictions`);
  64  |     await page.waitForLoadState('networkidle');
  65  |     const hasPredictions = await page.locator('h1, h2').count();
  66  |     expect(hasPredictions).toBeGreaterThan(0);
  67  |   });
  68  | 
  69  |   test('Prescriptions page loads', async ({ page }) => {
  70  |     await seedAuth(page);
  71  |     await page.goto(`${BASE}#/prescriptions`);
  72  |     await page.waitForLoadState('networkidle');
  73  |     const hasPrescriptions = await page.locator('h1, h2').count();
  74  |     expect(hasPrescriptions).toBeGreaterThan(0);
  75  |   });
  76  | 
  77  |   test('Hypothesis page loads', async ({ page }) => {
  78  |     await seedAuth(page);
  79  |     await page.goto(`${BASE}#/hypothesis`);
  80  |     await page.waitForLoadState('networkidle');
  81  |     const hasHypothesis = await page.locator('h1, h2').count();
  82  |     expect(hasHypothesis).toBeGreaterThan(0);
  83  |   });
  84  | 
  85  |   test('History page loads', async ({ page }) => {
  86  |     await seedAuth(page);
  87  |     await page.goto(`${BASE}#/history`);
  88  |     await page.waitForLoadState('networkidle');
  89  |     const hasHistory = await page.locator('h1, h2').count();
  90  |     expect(hasHistory).toBeGreaterThan(0);
  91  |   });
  92  | 
  93  |   test('Documents page loads', async ({ page }) => {
  94  |     await seedAuth(page);
  95  |     await page.goto(`${BASE}#/documents`);
  96  |     await page.waitForLoadState('networkidle');
  97  |     const hasDocs = await page.locator('h1, h2').count();
  98  |     expect(hasDocs).toBeGreaterThan(0);
  99  |   });
  100 | 
  101 |   test('Settings page loads with AI config', async ({ page }) => {
  102 |     await seedAuth(page);
  103 |     await page.goto(`${BASE}#/settings`);
  104 |     await page.waitForLoadState('networkidle');
  105 |     // Check AI Configuration tab is accessible
  106 |     const hasAIConfig = await page.getByText(/AI Configuration/i).count();
> 107 |     expect(hasAIConfig).toBeGreaterThan(0);
      |                         ^ Error: expect(received).toBeGreaterThan(expected)
  108 |   });
  109 | });
  110 | 
```