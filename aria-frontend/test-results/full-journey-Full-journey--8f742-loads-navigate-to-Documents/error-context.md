# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-journey.spec.cjs >> Full journey - every page loads >> navigate to Documents
- Location: tests\e2e\full-journey.spec.cjs:23:5

# Error details

```
ReferenceError: page is not defined
```

# Page snapshot

```yaml
- generic [ref=e2]:
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
        - button "Documents" [active] [ref=e51]
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
        - generic:
          - heading [level=1]
        - button "Search... ⌘K" [ref=e83]:
          - generic [ref=e87]: Search...
          - generic [ref=e88]: ⌘K
        - button "Toggle theme" [ref=e89]
        - button "Notifications" [ref=e92]
        - button "A" [ref=e98]
      - main [ref=e102]:
        - generic [ref=e104]:
          - generic [ref=e105]:
            - generic [ref=e106]:
              - generic [ref=e107]: Knowledge Base
              - heading "Documents" [level=1] [ref=e110]
              - paragraph [ref=e111]: Manage and search your uploaded PDF documents
            - generic [ref=e112]: 0 documents
          - generic [ref=e114]:
            - textbox "Search across all documents…" [ref=e116]
            - button "Search" [disabled] [ref=e117]
          - generic [ref=e118]:
            - generic [ref=e119]: 📄
            - heading "No documents yet" [level=3] [ref=e120]
            - paragraph [ref=e121]: Upload PDF documents from the Data Sources page to get started.
  - generic [ref=e122]:
    - generic [ref=e123]:
      - text: ✦
      - button "Dismiss notification" [ref=e124]: ✕
    - generic [ref=e125]:
      - text: ✦
      - button "Dismiss notification" [ref=e126]: ✕
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
  11 |   { name: 'Data', navText: 'Data', check: () => expect(page.locator('.premium-card')).toBeVisible({ timeout: 5000 }) },
> 12 |   { name: 'Documents', navText: 'Documents', check: () => expect(page.locator('.premium-card, h2')).toBeVisible({ timeout: 5000 }) },
     |                                                                  ^ ReferenceError: page is not defined
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