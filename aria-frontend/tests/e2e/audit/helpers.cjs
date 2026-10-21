// Shared helpers for the wiring audit. Synthetic data only (work/datasets).
const path = require("path");
const fs = require("fs");
const { expect } = require("@playwright/test");

const BASE = process.env.ARIA_BASE || "http://localhost:8000";
const DATASETS = process.env.ARIA_AUDIT_DATASETS
  || path.resolve(__dirname, "../../../../work/datasets");

// Correct answers come from work/datasets/expected_answers.json.
const SETS = {
  A: {
    kind: "csv", file: "dataset_A_sales_orders.csv",
    question: "What is the total amount?", expectText: "1,805,810.30",
    raw: ["order_id", "order_date", "customer_segment", "sales_channel",
          "product_category", "product_name", "unit_price", "discount_pct", "total_amount"],
  },
  C: {
    kind: "csv", file: "dataset_C_messy_txns.csv",
    question: "What is the total amt?", expectText: "1,071,222",
    raw: ["txn_id", "txn_dt", "cust_nm", "store_cd", "prod_cat", "prod_nm",
          "disc_pct", "pay_mthd", "dataset_c_messy_txns"],
  },
  B: {
    kind: "postgres", db: "aria_test", port: Number(process.env.ARIA_AUDIT_PG_PORT || 55432),
    question: "What is the total due?", expectText: "2,141,650.33",
    raw: ["SalesOrderHeader", "SalesOrderDetail", "TotalDue", "SubTotal", "LineTotal",
          "OrderQty", "CustomerID", "CategoryName", "CompanyName", "OrderStatus"],
  },
};

const PAGES = [
  { id: "dashboard", nav: "Dashboard" },
  { id: "analytics", nav: "AI Analytics" },
  { id: "insights", nav: "Insights" },
  { id: "intelligence", nav: "Intelligence" },
  { id: "predictive", nav: "Forecast" },
  { id: "data", nav: "Data" },
  { id: "documents", nav: "Documents" },
  { id: "copilot", nav: "Copilot" },
  { id: "history", nav: "History" },
  { id: "settings", nav: "Settings" },
];

const BENIGN_CONSOLE = [/favicon/i, /React DevTools/i, /Download the React DevTools/i];

/** Record console errors, page crashes, failed requests and HTTP >= 400. */
function attachSink(page) {
  const sink = { consoleErrors: [], pageErrors: [], httpErrors: [], requestFailures: [] };
  page.on("console", (m) => {
    if (m.type() === "error" && !BENIGN_CONSOLE.some((re) => re.test(m.text()))) {
      sink.consoleErrors.push(m.text().slice(0, 300));
    }
  });
  page.on("pageerror", (e) => sink.pageErrors.push(String(e.message).slice(0, 300)));
  page.on("response", (r) => {
    if (r.status() >= 400 && r.url().includes("/api/")) {
      sink.httpErrors.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`);
    }
  });
  page.on("requestfailed", (r) => {
    const why = r.failure()?.errorText || "";
    if (!/aborted|ERR_ABORTED/i.test(why)) {
      sink.requestFailures.push(`${r.method()} ${new URL(r.url()).pathname} ${why}`);
    }
  });
  return sink;
}

/** Sign in through the real form and pick Local AI. */
async function loginUI(page, email, pass) {
  await page.goto(BASE + "/");
  // A valid session cookie (set by registering through the API) restores
  // the session on boot, so the app may skip the login form by itself.
  // Let the boot session check settle before deciding what to do.
  const engine = page.getByText(/choose your ai engine/i);
  const dash = page.getByRole("button", { name: /dashboard/i }).first();
  // Give the boot session check (up to 10 s in App.tsx) time to move off
  // the login form on its own before typing into it.
  await engine.or(dash).first().waitFor({ timeout: 8000 }).catch(() => {});
  if (!(await engine.isVisible().catch(() => false)) && !(await dash.isVisible().catch(() => false))) {
    await page.locator("#login-email").fill(email);
    await page.locator("#login-password").fill(pass);
    await page.locator(".login-button").click();
  }
  if (!(await dash.isVisible().catch(() => false))) {
    await engine.waitFor({ timeout: 30000 });
    await page.getByText("Local AI", { exact: false }).first().click();
    await page.getByRole("button", { name: /^continue$/i }).click();
  }
  await expect(dash).toBeVisible({ timeout: 30000 });
}

async function registerAndLogin(page) {
  const id = "audit" + Date.now() + Math.floor(Math.random() * 1e4);
  const email = `${id}@aria.test`;
  const pass = "AuditPass123!";
  // The login form maps the email to a backend username exactly like
  // src/utils/authStorage.js toBackendUsername ("@" -> "_at_").
  const username = email.toLowerCase().replace(/@/g, "_at_").replace(/\+/g, "_plus_")
    .replace(/[^a-z0-9_.-]/g, "");
  const res = await page.request.post(BASE + "/api/auth/register",
    { data: { username, password: pass } });
  expect(res.ok(), "register API").toBeTruthy();
  await loginUI(page, email, pass);
  return { email, pass, username };
}

/** Connect a dataset through the real API using the page's own session. */
async function connectDataset(page, key, creds) {
  const ds = SETS[key];
  let res;
  if (ds.kind === "csv") {
    const file = path.join(DATASETS, ds.file);
    res = await page.request.post(BASE + "/api/connect_file", {
      multipart: { file: { name: ds.file, mimeType: "text/csv", buffer: fs.readFileSync(file) } },
      timeout: 180000,
    });
  } else {
    res = await page.request.post(BASE + "/api/connect", {
      data: { source_type: "relational", db_type: "postgresql", host: "localhost",
              port: ds.port, db: ds.db, user: "postgres", password: "audit-trust-auth",
              db_schema: "public" },
      timeout: 180000,
    });
  }
  const body = await res.text();
  expect(res.ok(), `connect ${key}: ${body.slice(0, 200)}`).toBeTruthy();
  // Reload: the app restores the signed-in session and the server-side
  // connection on boot. If a build still drops to the login form, sign in
  // again exactly as a user would.
  await page.reload();
  await page.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});
  const dash = page.getByRole("button", { name: /dashboard/i }).first();
  if (!(await dash.isVisible().catch(() => false))) {
    if (await page.getByText(/choose your ai engine/i).isVisible().catch(() => false)) {
      await page.getByText("Local AI", { exact: false }).first().click();
      await page.getByRole("button", { name: /^continue$/i }).click();
    } else {
      await loginUI(page, creds.email, creds.pass);
    }
  }
  await expect(dash).toBeVisible({ timeout: 30000 });
  await gotoPage(page, "Dashboard");
  // Guard: never test pages without data. The connected-source chip and
  // real cards must be present, not the "Connect a Data Source" empty state.
  await expect(page.getByText(/connect a data source/i), `dataset ${key} not shown after reload`)
    .toHaveCount(0, { timeout: 60000 });
}

async function gotoPage(page, nav) {
  await page.getByRole("button", { name: new RegExp(`^${nav}$`, "i") }).first().click();
  await page.waitForLoadState("networkidle", { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(1500);
}

async function setDark(page, dark) {
  const isDark = await page.evaluate(() => document.documentElement.classList.contains("dark"));
  if (isDark !== dark) {
    await page.getByRole("button", { name: dark ? /switch to dark mode/i : /switch to light mode/i }).click();
    await page.waitForTimeout(300);
  }
}

/** Visible-text problems: NaN/undefined/etc. and raw identifiers. */
async function textProblems(page, rawNames, { allowRaw = false } = {}) {
  const text = await page.locator("main").innerText().catch(() => "");
  const problems = [];
  const bad = text.match(/\b(NaN|undefined|Infinity)\b|\[object Object\]|\bnull\b/g);
  if (bad) problems.push(`bad tokens: ${[...new Set(bad)].join(", ")}`);
  if (/Something went wrong on this page/i.test(text)) problems.push("error boundary shown");
  if (!allowRaw) {
    const leaks = rawNames.filter((r) => new RegExp(`(?<![\\w])${r}(?![\\w])`).test(text));
    if (leaks.length) {
      // Show where each leak sits so the failure points at the UI text.
      const where = leaks.map((r) => {
        const i = text.search(new RegExp(`(?<![\\w])${r}(?![\\w])`));
        return `${r} in "…${text.slice(Math.max(0, i - 50), i + r.length + 30).replace(/\s+/g, " ")}…"`;
      });
      problems.push(`raw identifiers: ${where.join(" | ")}`);
    }
  }
  return problems;
}

/** Text contrast of h1/h2 against the page background (WCAG ratio). */
async function headingContrast(page) {
  return page.evaluate(() => {
    const lum = (c) => {
      const m = c.match(/\d+(\.\d+)?/g);
      if (!m) return null;
      const [r, g, b] = m.slice(0, 3).map(Number).map((v) => {
        v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * r + 0.7152 * g + 0.0722 * b;
    };
    const bgOf = (el) => {
      for (let e = el; e; e = e.parentElement) {
        const c = getComputedStyle(e).backgroundColor;
        if (c && !/rgba\(0, 0, 0, 0\)|transparent/.test(c)) return c;
      }
      return getComputedStyle(document.body).backgroundColor;
    };
    const out = [];
    for (const h of document.querySelectorAll("main h1, main h2")) {
      if (!h.offsetParent || !h.innerText.trim()) continue;
      const s = getComputedStyle(h);
      if (s.backgroundClip === "text" || s.webkitBackgroundClip === "text") continue;
      const a = lum(s.color), b = lum(bgOf(h));
      if (a == null || b == null) continue;
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      out.push({ text: h.innerText.trim().slice(0, 40), ratio: Math.round(ratio * 10) / 10 });
    }
    return out;
  });
}

module.exports = {
  BASE, SETS, PAGES, attachSink, registerAndLogin, loginUI, connectDataset, gotoPage, setDark,
  textProblems, headingContrast,
};
