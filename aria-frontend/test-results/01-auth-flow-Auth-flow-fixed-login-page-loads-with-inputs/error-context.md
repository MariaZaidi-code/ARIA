# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 01-auth-flow.spec.cjs >> Auth flow (fixed) >> login page loads with inputs
- Location: tests\e2e\01-auth-flow.spec.cjs:5:3

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
  1  | // CommonJS // Playwright e2e: Authentication flow (fixed)
  2  | const { test, expect } = require('@playwright/test');
  3  | 
  4  | test.describe('Auth flow (fixed)', () => {
  5  |   test('login page loads with inputs', async ({ page }) => {
  6  |     await page.goto('http://localhost:5174');
  7  |     await page.waitForLoadState('networkidle');
  8  |     const inputs = await page.locator('input').count();
> 9  |     expect(inputs).toBeGreaterThan(0);
     |                    ^ Error: expect(received).toBeGreaterThan(expected)
  10 |   });
  11 |   test('seeded auth lands on dashboard with sidebar', async ({ page }) => {
  12 |     await page.goto('http://localhost:5174');
  13 |     await page.waitForLoadState('networkidle');
  14 |     await page.evaluate(() => {
  15 |       localStorage.setItem('aria_auth_token', 'test_token_playwright_2024');
  16 |       localStorage.setItem('aria_auth_user', JSON.stringify({ email: 'test@aria.ai', username: 'Test' }));
  17 |       localStorage.setItem('aria_llm_mode', 'local');
  18 |       localStorage.setItem('aria_db_configured', 'true');
  19 |     });
  20 |     await page.reload();
  21 |     await page.waitForLoadState('networkidle');
  22 |     const sidebar = await page.locator('aside, nav, button').filter({ hasText: /Dashboard/i }).count();
  23 |     expect(sidebar).toBeGreaterThanOrEqual(0);
  24 |   });
  25 | });
  26 | 
```