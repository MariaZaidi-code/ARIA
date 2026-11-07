// CommonJS // Playwright e2e: Copilot page — welcome state, bubbles with
// formatted answers, thinking state, error + retry, provider switch + retry,
// history search/grouping/delete, phone drawer and dark mode. The Copilot
// APIs are mocked with synthetic data, so no database or AI engine is needed.
const { test, expect } = require('@playwright/test');
const { seedAuth } = require('./auth-helper');

const BASE = process.env.ARIA_E2E_BASE_URL || 'http://localhost:8000';

const ANSWER = {
  ok: true,
  answer: 'There are **1,200** orders in total.\n\n- North: 700\n- South: 500',
  sql: 'SELECT region, COUNT(*) AS orders FROM orders GROUP BY region',
  provider: 'local',
  data: [{ region: 'North', orders: 700 }, { region: 'South', orders: 500 }],
  chart: { type: 'bar', x: 'region', y: 'orders', reason: 'Orders by region' },
};

/** Install mocks; `state` is mutated by tests to drive scenarios. */
async function mockCopilot(page, state) {
  await page.route('**/api/copilot/suggestions', (route) => route.fulfill({
    json: { suggestions: ['How many orders are there?', 'Which region sells most?', 'Show monthly revenue', 'Top 5 products'] },
  }));
  await page.route('**/api/copilot', async (route) => {
    const body = JSON.parse(route.request().postData() || '{}');
    state.questions.push(body.question);
    const next = state.replies.shift() || { json: ANSWER };
    if (next.delayMs) await new Promise((resolve) => setTimeout(resolve, next.delayMs));
    if (next.abort) return route.abort('failed');
    return route.fulfill(next.status ? { status: next.status, json: next.json || {} } : { json: next.json });
  });
  await page.route('**/api/provider/switch', (route) => {
    state.switches.push(JSON.parse(route.request().postData() || '{}'));
    return route.fulfill({ json: { ok: true } });
  });
}

function freshState(replies = []) {
  return { questions: [], switches: [], replies };
}

/** Clear saved chats, then reload so the page mounts with the mocks. */
async function openCopilot(page) {
  await page.goto(`${BASE}#/copilot`);
  await page.evaluate(() => {
    for (const key of Object.keys(localStorage)) if (key.includes('copilot.chats')) localStorage.removeItem(key);
  });
  await page.reload();
  await expect(page.getByRole('heading', { name: 'ARIA Copilot' }).first()).toBeVisible({ timeout: 15000 });
}

const composer = (page) => page.getByPlaceholder(/ask aria anything about your data/i);

test.describe('Copilot page', () => {
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

  test('welcome state shows data suggestions and an empty history', async () => {
    const state = freshState();
    await mockCopilot(page, state);
    await openCopilot(page);
    await expect(page.getByText('No conversations yet')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Which region sells most?' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Send question' })).toBeDisabled();
    // The page fills the window even when empty: the composer sits at the bottom.
    const viewport = page.viewportSize();
    const composerBox = await page.locator('.cpl-composer').boundingBox();
    expect(composerBox.y + composerBox.height).toBeGreaterThan(viewport.height - 4);

    await page.getByRole('button', { name: 'How many orders are there?' }).click();
    await expect(page.getByRole('log', { name: 'Conversation' })).toContainText('How many orders are there?');
    expect(state.questions).toEqual(['How many orders are there?']);
  });

  test('answers render as formatted bubbles with chart, evidence and copy', async () => {
    const state = freshState();
    await mockCopilot(page, state);
    await openCopilot(page);
    await composer(page).fill('How many orders are there?');
    await composer(page).press('Enter');

    const log = page.getByRole('log', { name: 'Conversation' });
    await expect(log.locator('strong', { hasText: '1,200' })).toBeVisible();
    await expect(log.locator('li', { hasText: 'North: 700' })).toBeVisible();
    await expect(log).not.toContainText('**');
    await expect(log.getByText('Orders by region')).toBeVisible();
    await expect(log.getByText('Evidence')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Copy answer' })).toBeVisible();
    // The input box spans the same width as the message column (ChatGPT-style).
    const thread = await page.locator('.cpl-thread').boundingBox();
    const inputBox = await page.locator('.cpl-input-box').boundingBox();
    expect(Math.abs(inputBox.width - thread.width)).toBeLessThanOrEqual(2);
    expect(Math.abs(inputBox.x - thread.x)).toBeLessThanOrEqual(2);
    // Only the message list scrolls: the app's <main> never does, so the
    // header, history and composer stay on screen.
    const mainScroll = await page.locator('main').evaluate((el) => el.scrollHeight - el.clientHeight);
    expect(mainScroll).toBeLessThanOrEqual(1);
    await expect(page.locator('.cpl-sidebar-title h2')).toBeInViewport();
    await expect(composer(page)).toBeInViewport();
    // The chat is titled from the first question and listed under Today.
    const history = page.getByRole('navigation', { name: 'Saved conversations' });
    await expect(history.getByText('Today')).toBeVisible();
    const item = history.getByRole('button', { name: /^How many orders are there\?/ });
    await expect(item).toBeVisible();
    // The preview is plain text: no raw Markdown markers.
    await expect(item).toContainText('There are 1,200 orders in total.');
    await expect(item).not.toContainText('**');
  });

  test('shift+enter adds a line and sending is blocked while ARIA is thinking', async () => {
    const state = freshState([{ json: ANSWER, delayMs: 1500 }]);
    await mockCopilot(page, state);
    await openCopilot(page);
    await composer(page).fill('First line');
    await composer(page).press('Shift+Enter');
    await composer(page).type('second line');
    await expect(composer(page)).toHaveValue('First line\nsecond line');
    await composer(page).press('Enter');

    await expect(page.getByLabel('ARIA is thinking')).toBeVisible();
    await composer(page).fill('Another question');
    await expect(page.getByRole('button', { name: "Waiting for ARIA's answer" })).toBeDisabled();
    await composer(page).press('Enter');
    await expect(page.getByLabel('ARIA is thinking')).toHaveCount(0, { timeout: 10000 });
    expect(state.questions).toEqual(['First line\nsecond line']);
  });

  test('a failed request shows an error bubble that retries the same question', async () => {
    const state = freshState([{ abort: true }, { json: ANSWER }]);
    await mockCopilot(page, state);
    await openCopilot(page);
    await composer(page).fill('Revenue by region?');
    await composer(page).press('Enter');

    await expect(page.getByText('Something went wrong')).toBeVisible();
    await page.getByRole('button', { name: 'Try again', exact: true }).click();
    await expect(page.getByText('Something went wrong')).toHaveCount(0);
    await expect(page.getByRole('log', { name: 'Conversation' }).locator('strong', { hasText: '1,200' })).toBeVisible();
    expect(state.questions).toEqual(['Revenue by region?', 'Revenue by region?']);
    // The question is kept once; only the failed reply was replaced.
    await expect(page.locator('.cpl-bubble.user', { hasText: 'Revenue by region?' })).toHaveCount(1);
  });

  test('provider failure switches to on-device AI and retries', async () => {
    const state = freshState([
      { json: { ok: false, detail: 'The cloud AI provider could not be reached.' } },
      { json: ANSWER },
    ]);
    await mockCopilot(page, state);
    await openCopilot(page);
    await composer(page).fill('Total orders?');
    await composer(page).press('Enter');
    await page.getByRole('button', { name: /switch to on-device ai and retry/i }).click();
    await expect(page.getByRole('log', { name: 'Conversation' }).locator('strong', { hasText: '1,200' })).toBeVisible();
    expect(state.switches).toEqual([{ provider: 'local' }]);
    expect(state.questions).toEqual(['Total orders?', 'Total orders?']);
  });

  test('history search, switching and confirmed delete', async () => {
    const state = freshState();
    await mockCopilot(page, state);
    await openCopilot(page);
    for (const question of ['Orders by region', 'Monthly revenue trend']) {
      await page.getByRole('button', { name: 'New chat' }).first().click();
      await composer(page).fill(question);
      await composer(page).press('Enter');
      await expect(page.getByRole('button', { name: 'Copy answer' }).first()).toBeVisible();
    }
    const history = page.getByRole('navigation', { name: 'Saved conversations' });
    await expect(history.locator('.cpl-history-item')).toHaveCount(2);

    await page.getByLabel('Search conversations').fill('monthly');
    await expect(history.locator('.cpl-history-item')).toHaveCount(1);
    await page.getByLabel('Search conversations').fill('nothing like this');
    await expect(history.getByText('No matches')).toBeVisible();
    await page.getByLabel('Search conversations').fill('');

    await history.getByRole('button', { name: /^Orders by region/ }).click();
    await expect(page.locator('.cpl-header h2')).toHaveText('Orders by region');

    await page.getByRole('button', { name: 'Delete conversation Orders by region' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Delete this conversation?' });
    await dialog.getByRole('button', { name: 'Cancel' }).click();
    await expect(history.locator('.cpl-history-item')).toHaveCount(2);
    await page.getByRole('button', { name: 'Delete conversation Orders by region' }).click();
    await dialog.getByRole('button', { name: 'Delete' }).click();
    await expect(history.locator('.cpl-history-item')).toHaveCount(1);
    await expect(history).not.toContainText('Orders by region');
  });

  test('phone layout uses a history drawer and fits the screen in dark mode', async () => {
    const state = freshState();
    await mockCopilot(page, state);
    await page.setViewportSize({ width: 390, height: 780 });
    await openCopilot(page);
    await page.evaluate(() => document.documentElement.classList.add('dark'));
    await composer(page).fill('How many orders are there?');
    await composer(page).press('Enter');
    await expect(page.getByRole('button', { name: 'Copy answer' })).toBeVisible();

    const sidebar = page.locator('.cpl-sidebar');
    const hiddenBox = await sidebar.boundingBox();
    expect(hiddenBox.x + hiddenBox.width).toBeLessThanOrEqual(1);
    await page.getByRole('button', { name: 'Show conversation history' }).click();
    await expect.poll(async () => (await sidebar.boundingBox()).x).toBeGreaterThanOrEqual(-1);
    await page.keyboard.press('Escape');
    await expect.poll(async () => { const b = await sidebar.boundingBox(); return b.x + b.width; }).toBeLessThanOrEqual(1);

    // Nothing in the chat column overflows sideways at phone width.
    const overflow = await page.locator('.cpl-main').evaluate((el) => el.scrollWidth - el.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
    // Dark mode: the assistant bubble uses the dark card colour, not white.
    const bg = await page.locator('.cpl-bubble.assistant').first().evaluate((el) => getComputedStyle(el).backgroundColor);
    expect(bg).not.toBe('rgb(255, 255, 255)');
  });
});
