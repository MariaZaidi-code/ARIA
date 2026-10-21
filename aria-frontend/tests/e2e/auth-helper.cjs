// Shared Playwright helper: real backend auth + LLM selection.
// Single-host policy: everything runs against http://localhost:8000.
// No fake tokens: registers a throwaway user via the real API, signs in
// through the real login form, then picks the requested AI engine.
async function seedAuth(page, base = 'http://localhost:8000', mode = 'Local AI') {
  const user = 'pw' + Date.now() + Math.floor(Math.random() * 1e6);
  const email = `${user}@aria.test`;
  const pass = 'password123';
  // NOTE: the login form maps the email to the backend username exactly
  // like src/utils/authStorage.js toBackendUsername ("@" -> "_at_",
  // "+" -> "_plus_"), so register that exact name.
  const username = email.toLowerCase().replace(/@/g, '_at_').replace(/\+/g, '_plus_')
    .replace(/[^a-z0-9_.-]/g, '');
  const res = await page.request.post(base + '/api/auth/register', {
    data: { username, password: pass },
  });
  if (!res.ok()) {
    throw new Error('register failed: ' + (await res.text()).slice(0, 200));
  }
  await page.goto(base);
  // Registering via the API sets the session cookie, so the app may restore
  // the session on boot and skip the login form. Wait for whichever screen
  // the boot session check settles on (it takes up to 10 s).
  const engine = page.getByText('Choose your AI engine');
  await engine.waitFor({ timeout: 12000 }).catch(() => {});
  if (!(await engine.isVisible().catch(() => false))) {
    await page.locator('#login-email').fill(email);
    await page.locator('#login-password').fill(pass);
    await page.locator('.login-button').click();
  }
  await engine.waitFor({ timeout: 20000 });
  await page.getByText(mode, { exact: false }).first().click();
  await page.getByRole('button', { name: /continue/i }).click();
  await page.waitForLoadState('networkidle');
}

/** Connect a small synthetic CSV for the signed-in user, then reload so
 *  the app restores the session and the connection on boot (pages such as
 *  Intelligence only show their tools once data is connected). */
async function connectSampleCsv(page, base = 'http://localhost:8000') {
  const rows = ['order_date,region,product_category,total_amount'];
  const regions = ['North', 'South', 'East', 'West'];
  const cats = ['Office', 'Tech', 'Furniture'];
  for (let i = 0; i < 240; i++) {
    const m = String((i % 12) + 1).padStart(2, '0');
    const y = 2024 + Math.floor(i / 120);
    rows.push(`${y}-${m}-15,${regions[i % 4]},${cats[i % 3]},${100 + (i * 37) % 900}`);
  }
  const csv = Buffer.from(rows.join(String.fromCharCode(10)));
  const res = await page.request.post(base + '/api/connect_file', {
    multipart: { file: { name: 'e2e_sales.csv', mimeType: 'text/csv', buffer: csv } },
    timeout: 120000,
  });
  if (!res.ok()) throw new Error('connect failed: ' + (await res.text()).slice(0, 200));
  await page.reload();
  await page.getByRole('button', { name: /^dashboard$/i }).first().waitFor({ timeout: 30000 });
  await page.waitForLoadState('networkidle');
}

module.exports = { seedAuth, connectSampleCsv };
