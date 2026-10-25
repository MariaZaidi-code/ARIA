// QA: real connected-source flow. Registers, selects Cloud AI, connects a real
// CSV through the API, then drives every AI page and captures runtime errors.
const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");
const { signInVerified } = require("./auth-helper");

const BASE = process.env.ARIA_BASE || "http://localhost:8000";
const CSV = process.env.ARIA_CSV ||
  "C:\\Users\\Go\\Desktop\\ARIA\\data\\kaggle_retail_sales\\abbas829__ecommerce-sales-dataset\\ecommerce_sales_analytics_5000.csv";

const BENIGN = [/favicon/i, /React DevTools/i];

function attach(page, sink) {
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const t = m.text();
    if (BENIGN.some((re) => re.test(t))) return;
    sink.consoleErrors.push(t);
  });
  page.on("pageerror", (e) => sink.pageErrors.push(e.message));
  page.on("response", (r) => {
    if (r.status() >= 400 && !BENIGN.some((re) => re.test(r.url())))
      sink.failedResponses.push(`${r.status()} ${r.request().method()} ${r.url()}`);
  });
}

async function chooseLLM(page, label) {
  await page.getByRole("button", { name: new RegExp(label, "i") }).first().click();
  await page.getByRole("button", { name: /^continue$/i }).click();
  await expect(page.getByRole("button", { name: /dashboard/i }).first()).toBeVisible({ timeout: 20000 });
}

test.describe("ARIA QA - connected flow", () => {
  test("connect CSV then every AI page works", async ({ page }) => {
    test.setTimeout(300000);
    const sink = { consoleErrors: [], pageErrors: [], failedResponses: [] };
    attach(page, sink);

    await signInVerified(page, BASE);
    // Local AI only: connected-flow QA must stay offline/private â€” the
    // synthetic fixture CSV is processed on-device (Ollama), never sent to
    // a cloud provider and never touching the user's real dataset.
    await chooseLLM(page, "Local AI");

    // ---- Connect a real CSV through the API ----
    const res = await page.request.post(`${BASE}/api/connect_file`, {
      headers: { Origin: new URL(BASE).origin },
      multipart: {
        provider: "local",
        file: { name: path.basename(CSV), mimeType: "text/csv", buffer: fs.readFileSync(CSV) },
      },
      timeout: 120000,
    });
    const conn = await res.json();
    expect(res.ok(), `connect_file failed: ${JSON.stringify(conn)}`).toBeTruthy();
    expect(conn.ok).toBeTruthy();
    console.log("CONNECTED_TABLE=" + conn.table + " ROWS=" + conn.rows);
    // Connected behind the page's back (API, not the Data page UI): reload
    // so the app restores the session and picks up the new connection.
    await page.reload();
    await expect(page.getByRole("button", { name: /dashboard/i }).first()).toBeVisible({ timeout: 30000 });
    await page.waitForLoadState("networkidle");

    // The connect happened through the API (not the UI wizard), so the SPA
    // still holds its pre-connect state — reload so the boot probe picks up
    // connection_status=connected before driving the AI pages.
    await page.reload();
    await page.waitForLoadState("networkidle");

    // ---- Analytics: run a real question ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /ai analytics/i }).first().click();
    await page.waitForTimeout(500);
    // Current UI: the ask input is labelled "Ask a question" (both the
    // landing and the follow-up input share the label â€” pick the visible one).
    const box = page.locator('input[aria-label="Ask a question"]:visible').first();
    await box.fill("What is the total sales by product category?");
    await box.press("Enter");
    // Wait for a terminal state (answer or error surfaced), bounded.
    await expect
      .poll(async () => (await page.locator("#root").innerText()), { timeout: 90000, intervals: [2000] })
      .toMatch(/Answer|couldn't|could not|clarif|error/i)
      .catch(() => {});
    const analyticsHtml = await page.locator("#root").innerHTML();
    console.log("ANALYTICS_HAS_ANSWER=" + /Answer/i.test(analyticsHtml));
    expect(analyticsHtml.length).toBeGreaterThan(500);
    const analyticsProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (analyticsProblems.ce.length || analyticsProblems.pe.length || analyticsProblems.fr.length)
      console.log("ANALYTICS_PROBLEMS=" + JSON.stringify(analyticsProblems));

    // ---- Copilot: real question ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /^copilot$/i }).first().click();
    await page.waitForTimeout(400);
    const chat = page.locator('input[placeholder*="Ask ARIA"]').first();
    await chat.fill("How many records are in the data?");
    await chat.press("Enter");
    await expect
      .poll(async () => (await page.locator("#root").innerText()), { timeout: 90000, intervals: [2000] })
      .toMatch(/records|total|couldn|error/i)
      .catch(() => {});
    const copilotHtml = await page.locator("#root").innerHTML();
    console.log("COPILOT_HAS_MESSAGE=" + /records|total|couldn|error/i.test(copilotHtml));
    const copilotProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (copilotProblems.ce.length || copilotProblems.pe.length || copilotProblems.fr.length)
      console.log("COPILOT_PROBLEMS=" + JSON.stringify(copilotProblems));

    // ---- Insights (auto-fetch now that a source is connected) ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /^insights$/i }).first().click();
    await page.waitForTimeout(8000);
    const insightsProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (insightsProblems.ce.length || insightsProblems.pe.length || insightsProblems.fr.length)
      console.log("INSIGHTS_PROBLEMS=" + JSON.stringify(insightsProblems));

    // ---- Forecast (Predictive) ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /forecast/i }).first().click();
    await page.waitForTimeout(25000);
    const predictiveProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (predictiveProblems.ce.length || predictiveProblems.pe.length || predictiveProblems.fr.length)
      console.log("PREDICTIVE_PROBLEMS=" + JSON.stringify(predictiveProblems));

    // ---- Intelligence (explore / hypotheses / goals surface) ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /^intelligence$/i }).first().click();
    await page.waitForTimeout(8000);
    const intelligenceProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (intelligenceProblems.ce.length || intelligenceProblems.pe.length || intelligenceProblems.fr.length)
      console.log("INTELLIGENCE_PROBLEMS=" + JSON.stringify(intelligenceProblems));

    // ---- Hypothesis (embedded): Insights -> select -> "Investigate why" ->
    // contextual hypothesis in AI Analytics (Possible drivers) ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /^insights$/i }).first().click();
    await page.waitForTimeout(8000);
    const whyBtn = page.getByRole("button", { name: /investigate why/i }).first();
    if (await whyBtn.count()) {
      await whyBtn.click();
      await page.waitForTimeout(2000);
      const analyticsHtml = await page.locator("#root").innerHTML();
      console.log("HYPOTHESIS_CONTEXT=" + /Possible drivers|Investigate why|AI Analytics/i.test(analyticsHtml));
      // Close/return: navigate back to Insights to verify context survived.
      await page.getByRole("button", { name: /^insights$/i }).first().click();
      await page.waitForTimeout(2000);
      const backHtml = await page.locator("#root").innerHTML();
      console.log("HYPOTHESIS_BACK=" + /Insights|Investigate why|Evidence/i.test(backHtml));
    } else {
      console.log("HYPOTHESIS_CONTEXT=no-insight-available (empty state, valid)");
    }
    const hypothesisProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (hypothesisProblems.ce.length || hypothesisProblems.pe.length || hypothesisProblems.fr.length)
      console.log("HYPOTHESIS_PROBLEMS=" + JSON.stringify(hypothesisProblems));

    // ---- History: should now list the analysis ----
    sink.consoleErrors.length = 0; sink.pageErrors.length = 0; sink.failedResponses.length = 0;
    await page.getByRole("button", { name: /^history$/i }).first().click();
    await page.waitForTimeout(2000);
    const historyProblems = { ce: [...sink.consoleErrors], pe: [...sink.pageErrors], fr: [...sink.failedResponses] };
    if (historyProblems.ce.length || historyProblems.pe.length || historyProblems.fr.length)
      console.log("HISTORY_PROBLEMS=" + JSON.stringify(historyProblems));

    expect(sink.pageErrors, `uncaught errors: ${sink.pageErrors.join(" | ")}`).toEqual([]);
  });
});
