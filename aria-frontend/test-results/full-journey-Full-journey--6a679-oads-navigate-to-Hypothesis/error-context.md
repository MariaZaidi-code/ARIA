# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-journey.spec.cjs >> Full journey - every page loads >> navigate to Hypothesis
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
      - button "Hypothesis" [active] [ref=e41]
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
      - heading "Hypothesis" [level=1] [ref=e84]
      - button "Search... ⌘K" [ref=e85]:
        - generic [ref=e89]: Search...
        - generic [ref=e90]: ⌘K
      - button "Toggle theme" [ref=e91]
      - button "Notifications" [ref=e94]
      - button "A" [ref=e100]
    - main [ref=e104]:
      - generic [ref=e106]:
        - generic [ref=e107]:
          - heading "Hypothesis" [level=2] [ref=e108]
          - paragraph [ref=e109]: Test assumptions against your data.
        - generic [ref=e110]:
          - textbox "Does increasing discounts increase sales?" [ref=e114]
          - generic [ref=e115]:
            - generic [ref=e116]:
              - paragraph [ref=e117]: Dataset
              - combobox [ref=e119] [cursor=pointer]:
                - option "Sales Database" [selected]
                - option "CRM Database"
                - option "All Sources"
            - generic [ref=e120]:
              - paragraph [ref=e121]: Time Period
              - combobox [ref=e123] [cursor=pointer]:
                - option "Last 3 months"
                - option "Last 6 months"
                - option "Last 12 months" [selected]
                - option "Year to date"
          - generic [ref=e124]:
            - button "Test Hypothesis" [ref=e125]
            - button "Clear" [ref=e126]
        - generic [ref=e127]:
          - paragraph [ref=e128]: Try an example
          - generic [ref=e129]:
            - button "Does increasing discounts increase sales?" [ref=e130]
            - button "Do customers who buy Electronics return faster?" [ref=e131]
            - button "Is there a correlation between ad spend and revenue?" [ref=e132]
            - button "Do weekday orders have higher average value than weekend orders?" [ref=e133]
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
> 10 |   { name: 'Hypothesis', navText: 'Hypothesis', check: () => expect(page.locator('h2')).toContainText('Hypothesis') },
     |                                                                    ^ ReferenceError: page is not defined
  11 |   { name: 'Data', navText: 'Data', check: () => expect(page.locator('.premium-card')).toBeVisible({ timeout: 5000 }) },
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