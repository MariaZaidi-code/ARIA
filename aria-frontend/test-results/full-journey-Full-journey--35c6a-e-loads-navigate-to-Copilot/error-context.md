# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: full-journey.spec.cjs >> Full journey - every page loads >> navigate to Copilot
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
      - button "Data" [ref=e45]
      - button "Documents" [ref=e51]
      - button "Copilot" [active] [ref=e57]
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
      - heading "Copilot" [level=1] [ref=e84]
      - button "Search... ⌘K" [ref=e85]:
        - generic [ref=e89]: Search...
        - generic [ref=e90]: ⌘K
      - button "Toggle theme" [ref=e91]
      - button "Notifications" [ref=e94]
      - button "A" [ref=e100]
    - main [ref=e104]:
      - generic [ref=e106]:
        - generic [ref=e107]:
          - generic [ref=e109]:
            - paragraph [ref=e110]: Conversations
            - button [ref=e111]
          - generic [ref=e113]:
            - button [ref=e114]:
              - paragraph [ref=e115]: Electronics revenue analysis
              - paragraph [ref=e116]: Sales Database · 4 messages
              - paragraph [ref=e117]: Today
            - button [ref=e118]:
              - paragraph [ref=e119]: Q3 performance review
              - paragraph [ref=e120]: Sales Database · 6 messages
              - paragraph [ref=e121]: Yesterday
            - button [ref=e122]:
              - paragraph [ref=e123]: Customer segmentation
              - paragraph [ref=e124]: CRM Database · 3 messages
              - paragraph [ref=e125]: Dec 28
            - button [ref=e126]:
              - paragraph [ref=e127]: Pricing strategy analysis
              - paragraph [ref=e128]: Sales Database · 5 messages
              - paragraph [ref=e129]: Dec 24
        - generic [ref=e130]:
          - generic [ref=e131]:
            - generic [ref=e132]:
              - paragraph [ref=e133]: Electronics revenue analysis
              - paragraph [ref=e134]: Sales Database · 4 messages
            - button [ref=e135]
          - generic [ref=e140]:
            - generic [ref=e141]:
              - generic [ref=e142]: A
              - generic [ref=e143]:
                - paragraph [ref=e145]: Show me revenue for Electronics last quarter.
                - paragraph [ref=e146]: 10:02 AM
            - generic [ref=e152]:
              - generic [ref=e153]:
                - paragraph [ref=e154]: Electronics generated $3.72M in Q3 2025, representing a 23.4% increase year-over-year. It was the top-performing category by both absolute revenue and growth rate.
                - paragraph [ref=e156]: Electronics Revenue · Jul-Dec 2025
              - paragraph [ref=e161]: 10:02 AM
            - generic [ref=e162]:
              - generic [ref=e163]: A
              - generic [ref=e164]:
                - paragraph [ref=e166]: Why did it decrease in August?
                - paragraph [ref=e167]: 10:03 AM
            - generic [ref=e173]:
              - paragraph [ref=e175]: "The August dip in Electronics revenue (from $310K to... wait, it actually increased from $290K in July to $310K in August). Looking at the data more carefully: Electronics grew consistently throughout Q3. The slight moderation in August growth rate (vs July) was likely due to a normal post-Prime Day cooldown — a well-documented seasonal pattern in consumer electronics."
              - paragraph [ref=e176]: 10:03 AM
          - generic [ref=e177]:
            - button "What are the top revenue drivers this quarter?" [ref=e178]
            - button "Show me year-over-year growth by category" [ref=e179]
            - button "Which customers have churned recently?" [ref=e180]
            - button "Summarize last week's performance" [ref=e181]
          - generic [ref=e183]:
            - textbox "Ask ARIA anything about your data..." [ref=e184]
            - button [ref=e185]
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
  12 |   { name: 'Documents', navText: 'Documents', check: () => expect(page.locator('.premium-card, h2')).toBeVisible({ timeout: 5000 }) },
> 13 |   { name: 'Copilot', navText: 'Copilot', check: () => expect(page.locator('textarea, input')).toBeVisible({ timeout: 5000 }) },
     |                                                              ^ ReferenceError: page is not defined
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