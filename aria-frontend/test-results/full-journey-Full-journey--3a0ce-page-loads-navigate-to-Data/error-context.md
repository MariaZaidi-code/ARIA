# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-journey.spec.cjs >> Full journey - every page loads >> navigate to Data
- Location: tests\e2e\full-journey.spec.cjs:23:5

# Error details

```
ReferenceError: page is not defined
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
      - button "Data" [active] [ref=e45]
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
      - heading "Data" [level=1] [ref=e84]
      - button "Search... ⌘K" [ref=e85]:
        - generic [ref=e89]: Search...
        - generic [ref=e90]: ⌘K
      - button "Toggle theme" [ref=e91]
      - button "Notifications" [ref=e94]
      - button "A" [ref=e100]
    - main [ref=e104]:
      - generic [ref=e106]:
        - generic [ref=e107]:
          - heading "Data Sources" [level=2] [ref=e108]
          - paragraph [ref=e109]: Connect a database, upload a CSV, or import a PDF — ARIA analyzes everything.
        - generic [ref=e110]:
          - button "Connected Sources" [ref=e111]
          - button "Schema" [ref=e112]
          - button "Data Preview" [ref=e113]
          - button "Data Quality" [ref=e114]
        - generic [ref=e116]:
          - paragraph [ref=e117]: Choose a data source
          - generic [ref=e120]:
            - button "PostgreSQL Database Connect to a PostgreSQL database for full analytics." [ref=e121] [cursor=pointer]:
              - generic [ref=e128]:
                - generic [ref=e129]:
                  - paragraph [ref=e130]: PostgreSQL
                  - generic [ref=e131]: Database
                - paragraph [ref=e132]: Connect to a PostgreSQL database for full analytics.
            - button "MySQL Database Connect to a MySQL database for full analytics." [ref=e133] [cursor=pointer]:
              - generic [ref=e141]:
                - generic [ref=e142]:
                  - paragraph [ref=e143]: MySQL
                  - generic [ref=e144]: Database
                - paragraph [ref=e145]: Connect to a MySQL database for full analytics.
            - button "CSV File File Upload Upload a structured CSV dataset for analysis." [ref=e146] [cursor=pointer]:
              - generic [ref=e153]:
                - generic [ref=e154]:
                  - paragraph [ref=e155]: CSV File
                  - generic [ref=e156]: File Upload
                - paragraph [ref=e157]: Upload a structured CSV dataset for analysis.
            - button "PDF Document File Upload Upload a PDF document for AI-powered extraction." [ref=e158] [cursor=pointer]:
              - generic [ref=e165]:
                - generic [ref=e166]:
                  - paragraph [ref=e167]: PDF Document
                  - generic [ref=e168]: File Upload
                - paragraph [ref=e169]: Upload a PDF document for AI-powered extraction.
```

# Test source

```ts
  1  | // CommonJS // Playwright: full journey through all ARIA pages (Figma layer + main)
  2  | const { test, expect } = require('@playwright/test');
  3  | 
  4  | const PAGES = [
  5  |   { name: 'Dashboard', navText: 'Dashboard', check: () => expect(page.locator('h2')).toContainText('Dashboard') },
  6  |   { name: 'AIAnalytics', navText: 'AI Analytics', check: () => expect(page.locator('h2')).toContainText('Analytics') },
  7  |   { name: 'Insights', navText: 'Insights', check: () => expect(page.locator('h2')).toContainText('Insight') },
  8  |   { name: 'Predictive', navText: 'Predictive', check: () => expect(page.locator('h2')).toContainText('Predictive') },
  9  |   { name: 'Prescription', navText: 'Prescription', check: () => expect(page.locator('h2')).toContainText('Prescription') },
  10 |   { name: 'Hypothesis', navText: 'Hypothesis', check: () => expect(page.locator('h2')).toContainText('Hypothesis') },
> 11 |   { name: 'Data', navText: 'Data', check: () => expect(page.locator('.premium-card')).toBeVisible({ timeout: 5000 }) },
     |                                                        ^ ReferenceError: page is not defined
  12 |   { name: 'Documents', navText: 'Documents', check: () => expect(page.locator('.premium-card, h2')).toBeVisible({ timeout: 5000 }) },
  13 |   { name: 'Copilot', navText: 'Copilot', check: () => expect(page.locator('textarea, input')).toBeVisible({ timeout: 5000 }) },
  14 |   { name: 'History', navText: 'History', check: () => expect(page.locator('h2')).toContainText('History') },
  15 |   { name: 'Settings', navText: 'Settings', check: () => expect(page.locator('.nav-item')).toHaveCount(7) },
  16 | ];
  17 | 
  18 | test.describe('Full journey - every page loads', () => {
  19 |   let page;
  20 |   test.beforeAll(async ({ browser }) => { page = await browser.newPage(); await page.goto('http://localhost:5174'); await page.waitForLoadState('networkidle'); });
  21 | 
  22 |   for (const p of PAGES) {
  23 |     test(`navigate to ${p.name}`, async () => {
  24 |       await page.getByRole('button', { name: new RegExp(p.navText, 'i') }).click();
  25 |       await page.waitForTimeout(300);
  26 |       await p.check();
  27 |     });
  28 |   }
  29 | });
  30 | 
```