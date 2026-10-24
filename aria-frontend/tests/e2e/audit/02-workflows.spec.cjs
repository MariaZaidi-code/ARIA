// User journeys traced end to end (UI -> API -> database -> UI), each checked
// against known-correct answers from work/datasets/expected_answers.json.
const path = require("path");
const { test, expect } = require("@playwright/test");
const {
  BASE, SETS, attachSink, registerAndLogin, connectDataset, gotoPage, setDark, textProblems, textIssues,
} = require("./helpers.cjs");

const DATASETS = process.env.ARIA_AUDIT_DATASETS || path.resolve(__dirname, "../../../../work/datasets");

function noServerErrors(sink) {
  expect.soft(sink.pageErrors, "JavaScript errors").toEqual([]);
  expect.soft(sink.httpErrors.filter((e) => /^5\d\d/.test(e)), "server errors").toEqual([]);
}

test("auth: register in UI, sign out, wrong password, sign in, session survives reload", async ({ page }) => {
  const sink = attachSink(page);
  const id = "audui" + Date.now();
  const email = `${id}@aria.test`;
  const chooseEngine = async () => {
    await page.getByText(/choose your ai engine/i).waitFor({ timeout: 30000 });
    await page.getByText("Local AI").first().click();
    await page.getByRole("button", { name: /^continue$/i }).click();
    await expect(page.getByRole("button", { name: /dashboard/i }).first()).toBeVisible({ timeout: 30000 });
  };
  const signOut = async () => {
    await page.locator("header button").filter({ hasText: /^\s*[A-Z]\s*$/ }).last().click();
    await page.getByText("Sign out").click();
    await expect(page.locator("#login-email")).toBeVisible({ timeout: 20000 });
  };
  await page.goto(BASE + "/");
  await test.step("register through the form signs the user in", async () => {
    await page.getByRole("button", { name: /create account/i }).first().click();
    await page.locator("#login-email").fill(email);
    await page.locator("#login-password").fill("AuditPass123!");
    await page.locator("#login-confirm").fill("AuditPass123!");
    await page.locator(".login-button").click();
    await chooseEngine();
  });
  await test.step("sign out returns to login", signOut);
  await test.step("wrong password is refused with a message", async () => {
    await page.locator("#login-email").fill(email);
    await page.locator("#login-password").fill("WrongPass999!");
    await page.locator(".login-button").click();
    await expect(page.getByRole("alert").first()).toBeVisible();
  });
  await test.step("correct password signs in", async () => {
    await page.locator("#login-password").fill("AuditPass123!");
    await page.locator(".login-button").click();
    await Promise.race([
      page.getByText(/choose your ai engine/i).waitFor({ timeout: 30000 }).then(chooseEngine),
      expect(page.getByRole("button", { name: /dashboard/i }).first()).toBeVisible({ timeout: 30000 }),
    ]);
    await expect(page.getByRole("button", { name: /dashboard/i }).first()).toBeVisible({ timeout: 30000 });
  });
  await test.step("session survives a reload", async () => {
    await page.reload();
    await expect(page.getByRole("button", { name: /dashboard/i }).first()).toBeVisible({ timeout: 30000 });
  });
  noServerErrors(sink);
});

test("data: upload a CSV through the Data page UI", async ({ page }) => {
  const sink = attachSink(page);
  await registerAndLogin(page);
  await gotoPage(page, "Data");
  await page.getByText("CSV File", { exact: true }).first().click();
  await page.locator('input[type=file][accept*="csv"]').setInputFiles(
    path.join(DATASETS, "dataset_A_sales_orders.csv"));
  await page.getByRole("button", { name: /upload & analyze csv/i }).click();
  await expect(page.getByText(/uploaded file/i).first()).toBeVisible({ timeout: 180000 });
  await expect(page.getByText(/11 columns/).first()).toBeVisible();
  for (const tab of ["Schema", "Data Preview", "Data Quality"]) {
    await page.getByRole("button", { name: new RegExp(tab, "i") }).first().click();
    await page.waitForTimeout(1500);
    await expect(page.getByText(/Something went wrong on this page/i)).toHaveCount(0);
  }
  noServerErrors(sink);
});

test("documents: upload a PDF, find it, search it and ask about it", async ({ page }) => {
  // Synthetic policy with known facts: 45-day returns, 12,500-unit warehouse.
  const sink = attachSink(page);
  await registerAndLogin(page);
  await test.step("upload through the Data page", async () => {
    await gotoPage(page, "Data");
    await page.getByText("PDF Document", { exact: true }).first().click();
    await page.locator('input[type=file][accept*="pdf"]').setInputFiles(
      path.join(__dirname, "fixtures", "aria_test_policy.pdf"));
    await page.getByRole("button", { name: /upload & analyze pdf/i }).click();
    await expect(page.getByText(/processing/i)).toHaveCount(0, { timeout: 180000 });
    await expect(page.getByText(/upload failed|couldn.?t|something went wrong/i)).toHaveCount(0);
  });
  await test.step("listed on the Documents page", async () => {
    await gotoPage(page, "Documents");
    await expect(page.getByText(/aria_test_policy/i).first()).toBeVisible({ timeout: 120000 });
    expect(await textProblems(page, [])).toEqual([]);
  });
  await test.step("search finds the refund policy", async () => {
    const box = page.getByPlaceholder(/search across all documents/i);
    await box.fill("refund");
    await box.press("Enter");
    await expect(page.getByText(/45 days/i).first()).toBeVisible({ timeout: 60000 });
  });
  noServerErrors(sink);
});

test("documents: ask questions about an uploaded PDF", async ({ page }) => {
  // KNOWN GAP (2026-10-24): on this branch document questions go to Copilot,
  // which replies "The schema for this connection is not available yet"
  // for a PDF connection. Maria's newer maria commit 92367d3 adds
  // "Ask your documents" (/api/documents/ask). Marked as an expected failure
  // so the suite stays honest: Playwright reports it as soon as it passes.
  test.fail(true, "Document Q&A not on this branch yet (see report section 7)");
  const sink = attachSink(page);
  await registerAndLogin(page);
  await gotoPage(page, "Data");
  await page.getByText("PDF Document", { exact: true }).first().click();
  await page.locator('input[type=file][accept*="pdf"]').setInputFiles(
    path.join(__dirname, "fixtures", "aria_test_policy.pdf"));
  await page.getByRole("button", { name: /upload & analyze pdf/i }).click();
  await expect(page.getByText(/processing/i)).toHaveCount(0, { timeout: 180000 });
  await gotoPage(page, "Copilot");
  const box = page.getByPlaceholder(/ask aria anything about your data/i);
  await box.fill("How many days do customers have to return items?");
  await box.press("Enter");
  await expect(page.getByText(/\b45\b/).last()).toBeVisible({ timeout: 60000 });
  await box.fill("How many units can the warehouse store?");
  await box.press("Enter");
  await expect(page.getByText(/12,?500/).last()).toBeVisible({ timeout: 60000 });
  noServerErrors(sink);
});

test("analytics: autocomplete, ask, correct answer, Show SQL, follow-up", async ({ page }) => {
  const sink = attachSink(page);
  const creds = await registerAndLogin(page);
  await connectDataset(page, "C", creds);
  await gotoPage(page, "AI Analytics");
  const box = page.getByPlaceholder(/why did revenue drop/i);
  await test.step("autocomplete continues the typed text, one list only", async () => {
    await box.click();
    await box.pressSequentially("what is", { delay: 60 });
    const options = page.getByRole("option");
    await expect(options.first()).toBeVisible({ timeout: 15000 });
    await expect(options.first()).toHaveText(/^What is/i);
    expect(await page.locator("[role=option]:visible").evaluateAll(
      (els) => new Set(els.map((e) => e.parentElement)).size)).toBe(1);
  });
  await test.step("question returns the correct total", async () => {
    await box.fill(SETS.C.question);
    await box.press("Enter");
    await expect(page.getByText(SETS.C.expectText).first()).toBeVisible({ timeout: 120000 });
  });
  await test.step("Show SQL reveals the executed query", async () => {
    await page.getByRole("button", { name: /sql behind this answer|show sql/i }).first().click();
    await expect(page.getByText(/SUM\("amt"\)/).first()).toBeVisible();
  });
  await test.step("a follow-up suggestion runs", async () => {
    const chip = page.getByRole("button", { name: /^(What is|Which|How has)/ }).first();
    const label = (await chip.innerText()).trim();
    await chip.click();
    await expect(page.getByText(label.replace(/\?$/, "")).first()).toBeVisible({ timeout: 60000 });
  });
  noServerErrors(sink);
});

for (const key of ["A", "C", "B"]) {
  test(`ask ARIA, Copilot and Analytics agree on dataset ${key}`, async ({ page }) => {
    const sink = attachSink(page);
    const creds = await registerAndLogin(page);
    await connectDataset(page, key, creds);
    const ds = SETS[key];
    await test.step("Copilot page", async () => {
      await gotoPage(page, "Copilot");
      const box = page.getByPlaceholder(/ask aria anything about your data/i);
      await box.fill(ds.question);
      await box.press("Enter");
      await expect(page.getByText(ds.expectText).first()).toBeVisible({ timeout: 120000 });
    });
    await test.step("floating Ask ARIA bot", async () => {
      await gotoPage(page, "Dashboard");
      await page.getByRole("button", { name: /open ask aria/i }).first().click();
      const box = page.getByLabel(/ask aria a question/i);
      await box.fill(ds.question);
      await box.press("Enter");
      await expect(page.getByText(ds.expectText).first()).toBeVisible({ timeout: 120000 });
    });
    await test.step("Analytics page", async () => {
      await gotoPage(page, "AI Analytics");
      const box = page.getByPlaceholder(/why did revenue drop|ask another question/i).first();
      await box.fill(ds.question);
      await box.press("Enter");
      await expect(page.getByText(ds.expectText).first()).toBeVisible({ timeout: 120000 });
    });
    noServerErrors(sink);
  });
}

test("dashboard: cards show the right totals and 'Ask about this' hands off", async ({ page }) => {
  const sink = attachSink(page);
  const creds = await registerAndLogin(page);
  await connectDataset(page, "C", creds);
  await gotoPage(page, "Dashboard");
  await expect(page.getByText("Total Amount").first()).toBeVisible({ timeout: 60000 });
  await expect(page.getByText("1,500").first()).toBeVisible();          // Total Records
  await page.getByRole("button", { name: "Ask ARIA about Total Amount", exact: true }).first().click();
  await expect(page.getByText(/what should i know about total amount/i).first()).toBeVisible({ timeout: 30000 });
  await expect(page.getByText(SETS.C.expectText).first()).toBeVisible({ timeout: 120000 });
  noServerErrors(sink);
});

test("ask ARIA explains the dashboard with the numbers on screen", async ({ page }) => {
  const sink = attachSink(page);
  const creds = await registerAndLogin(page);
  await connectDataset(page, "C", creds);
  await gotoPage(page, "Dashboard");
  const card = page.locator('[role="button"]').filter({ hasText: "Total Amount" }).first();
  await expect(card).toBeVisible({ timeout: 60000 });
  await page.waitForTimeout(1500); // card numbers animate in
  const shown = ((await card.innerText()).match(/Total Amount\s+([\d.,]+[KM]?)/) || [])[1];
  expect(shown, "Total Amount value read from the card").toBeTruthy();

  await page.getByRole("button", { name: "Open Ask ARIA" }).last().click();
  const bot = page.getByRole("dialog", { name: "Ask ARIA" });
  const footnotes = bot.getByText("Explained from what's on your screen");
  const ask = async (q) => {
    const input = bot.getByLabel("Ask ARIA a question");
    await input.fill(q);
    await expect(input).toHaveValue(q);
    // Click Send once the typed text has registered (pressing Enter in the
    // same instant the panel reopens can submit an empty box).
    await bot.getByRole("button", { name: "Send question" }).click();
  };

  await test.step("dashboard starters are offered", async () => {
    await expect(bot.getByRole("button", { name: "Explain this dashboard" })).toBeVisible({ timeout: 15000 });
  });
  await test.step("'Explain this dashboard' walks through the cards with their values", async () => {
    await bot.getByRole("button", { name: "Explain this dashboard" }).click();
    await expect(bot.getByText(/This is your Dashboard/)).toBeVisible();
    await expect(bot.getByText(new RegExp(`Total Amount: ${shown.replace(".", "\\.")}`))).toBeVisible();
    await expect(footnotes).toHaveCount(1);
  });
  await test.step("a card is explained with the same value and the exact total", async () => {
    await ask("What does Total Amount mean?");
    await expect(bot.getByText(new RegExp(`Total Amount is ${shown.replace(".", "\\.")} \\(exactly 1,071,222\\)`))).toBeVisible();
  });
  await test.step("words on the screen are explained", async () => {
    await ask("what does the % next to the number mean?");
    await expect(bot.getByText(/The arrow and percentage show change/)).toBeVisible();
    await ask("What is data quality?");
    await expect(bot.getByText(/Data quality \d+(\.\d+)?% measures/)).toBeVisible();
  });
  await test.step("a chart is explained", async () => {
    await ask("explain the amount by month chart");
    await expect(bot.getByText(/"Amount by Month" shows amount for each month/)).toBeVisible();
    await expect(footnotes).toHaveCount(5);
  });
  await test.step("data questions still go to the data engine", async () => {
    await ask("What is the total amt?");
    // The engine's own wording ("Total amount is 1,071,222 ..."), not the
    // earlier screen explanation that also mentions the exact total.
    await expect(bot.getByText(/Total amount is 1,071,222/)).toBeVisible({ timeout: 120000 });
    await expect(footnotes, "data answer must not be marked as a screen explanation").toHaveCount(5);
  });
  await test.step("readable in light and dark mode", async () => {
    await bot.screenshot({ path: test.info().outputPath("bot-light.png") });
    await page.keyboard.press("Escape");
    await setDark(page, true);
    await page.getByRole("button", { name: "Open Ask ARIA" }).last().click();
    await ask("Explain this dashboard");
    await expect(footnotes).toHaveCount(6);
    await bot.screenshot({ path: test.info().outputPath("bot-dark.png") });
  });
  noServerErrors(sink);
});

for (const key of ["A", "C", "B"]) {
  test(`prescriptions: feed and case drawer on dataset ${key}`, async ({ page }) => {
    const sink = attachSink(page);
    const creds = await registerAndLogin(page);
    await connectDataset(page, key, creds);
    await gotoPage(page, "Intelligence");
    await page.getByRole("tab", { name: /prescriptions/i }).click();
    await expect(page.getByText("What needs attention").first()).toBeVisible({ timeout: 30000 });

    const cardOpen = page.getByRole("button", { name: /^Open case:/ });
    const empty = page.getByText(/nothing needs attention right now/i);
    await test.step("feed settles on cards or an honest empty state, never an error", async () => {
      await expect(cardOpen.first().or(empty.first())).toBeVisible({ timeout: 180000 });
      await expect(page.getByText(/couldn.?t|something went wrong|failed to fetch/i)).toHaveCount(0);
      expect(await textProblems(page, SETS[key].raw)).toEqual([]);
    });
    if (!(await cardOpen.first().isVisible().catch(() => false))) {
      test.info().annotations.push({ type: "note", description: `dataset ${key}: no cases (empty state shown)` });
      noServerErrors(sink);
      return;
    }

    await test.step("case drawer: plain wording, real figures, closes cleanly", async () => {
      await cardOpen.first().click();
      const drawer = page.getByRole("dialog", { name: /^Case:/ });
      await expect(drawer).toBeVisible();
      const text = await drawer.innerText();
      expect(textIssues(text, SETS[key].raw)).toEqual([]);
      expect(text, "the case shows at least one figure").toMatch(/\d/);
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
    });

    await test.step("tracking a case: track, mark achieved, stop tracking", async () => {
      await cardOpen.first().click();
      const drawer = page.getByRole("dialog", { name: /^Case:/ });
      const track = drawer.getByRole("button", { name: "Track this action" });
      if (!(await track.isVisible().catch(() => false))) return; // already tracked
      await track.click();
      await page.keyboard.press("Escape").catch(() => {});
      const achieved = page.getByRole("button", { name: /^Mark achieved:/ }).first();
      await expect(achieved).toBeVisible({ timeout: 30000 });
      await achieved.click();
      const stop = page.getByRole("button", { name: /^Stop tracking:/ }).first();
      await stop.click();
      await expect(page.getByText(/couldn.?t save|failed to fetch/i)).toHaveCount(0);
    });
    noServerErrors(sink);
  });
}

test("intelligence: every tab opens and Explore runs", async ({ page }) => {
  const sink = attachSink(page);
  const creds = await registerAndLogin(page);
  await connectDataset(page, "A", creds);
  await gotoPage(page, "Intelligence");
  for (const tab of ["Explore", "Hypotheses", "Goals", "Prescriptions", "What-If", "Reports"]) {
    await test.step(tab, async () => {
      await page.getByRole("tab", { name: new RegExp(`^${tab}$`, "i") }).first().click()
        .catch(() => page.getByRole("button", { name: new RegExp(`^${tab}$`, "i") }).first().click());
      await page.waitForTimeout(2000);
      await expect(page.getByText(/Something went wrong on this page/i)).toHaveCount(0);
    });
  }
  await test.step("Explore -> Run Analysis", async () => {
    await page.getByRole("tab", { name: /^explore$/i }).first().click()
      .catch(() => page.getByRole("button", { name: /^explore$/i }).first().click());
    await page.getByRole("button", { name: /run analysis/i }).click();
    await expect(page.getByRole("button", { name: /run analysis/i })).toBeEnabled({ timeout: 120000 });
    await expect(page.getByText(/Something went wrong on this page/i)).toHaveCount(0);
  });
  noServerErrors(sink);
});

test("forecast, insights, documents, history and settings work", async ({ page }) => {
  const sink = attachSink(page);
  const creds = await registerAndLogin(page);
  await connectDataset(page, "A", creds);
  await test.step("Forecast renders a setup and a result or an honest message", async () => {
    await gotoPage(page, "Forecast");
    await expect(page.getByText(/forecast setup/i).first()).toBeVisible({ timeout: 60000 });
  });
  await test.step("Forecast details are plain English (no math jargon), also when expanded", async () => {
    // Open every collapsed detail: confidence panel, evidence and its
    // "Technical details" box, then check the visible text.
    const conf = page.getByRole("button", { name: /forecast confidence/i }).first();
    await expect(conf).toBeVisible({ timeout: 120000 });
    await conf.click();
    await expect(page.getByText(/typical miss/i).first()).toBeVisible();
    const evidence = page.getByRole("button", { name: /^evidence/i }).first();
    if (await evidence.isVisible().catch(() => false)) {
      await evidence.click();
      const tech = page.locator("summary", { hasText: /technical details/i }).first();
      if (await tech.isVisible().catch(() => false)) await tech.click();
    }
    expect(await textProblems(page, SETS.A.raw, { allowRaw: false })).toEqual([]);
  });
  await test.step("Insights lists insights or an empty state", async () => {
    await gotoPage(page, "Insights");
    await expect(page.getByText(/what did aria learn today/i).first()).toBeVisible({ timeout: 60000 });
  });
  await test.step("Documents shows its empty state", async () => {
    await gotoPage(page, "Documents");
    await expect(page.getByText(/no documents yet/i).first()).toBeVisible();
  });
  await test.step("History records an asked question", async () => {
    await gotoPage(page, "AI Analytics");
    const box = page.getByPlaceholder(/why did revenue drop/i);
    await box.fill(SETS.A.question);
    await box.press("Enter");
    await expect(page.getByText(SETS.A.expectText).first()).toBeVisible({ timeout: 120000 });
    await gotoPage(page, "History");
    await expect(page.getByText(/total amount/i).first()).toBeVisible({ timeout: 30000 });
  });
  await test.step("Settings: every tab opens, profile saves", async () => {
    await gotoPage(page, "Settings");
    for (const tab of ["Appearance", "AI Configuration", "Data Sources", "Workspace",
                       "Notifications", "Privacy", "Application", "Profile"]) {
      await page.getByRole("button", { name: new RegExp(`^${tab}$`, "i") }).first().click();
      await page.waitForTimeout(600);
      await expect(page.getByText(/Something went wrong on this page/i)).toHaveCount(0);
    }
    await page.getByRole("button", { name: /save changes/i }).click();
    await expect(page.getByRole("status").filter({ hasText: /profile saved/i })).toBeVisible();
  });
  await test.step("dark theme persists across reload", async () => {
    await setDark(page, true);
    await page.reload({ waitUntil: "domcontentloaded" });
    // Checked on whatever screen the reload lands on (currently the login
    // form - see the session-reload finding): the theme must still be dark.
    expect(await page.evaluate(() => document.documentElement.classList.contains("dark"))).toBe(true);
  });
  noServerErrors(sink);
});
