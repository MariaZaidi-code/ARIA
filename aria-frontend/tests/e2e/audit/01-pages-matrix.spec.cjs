// Every page x light/dark x dataset (A snake CSV, C shorthand CSV, B CamelCase
// PostgreSQL). Per page: renders without crash, no NaN/undefined/null/raw
// identifiers in visible text, readable headings, no 5xx or page errors.
// A screenshot of every cell is saved; findings are attached as JSON.
const { test, expect } = require("@playwright/test");
const {
  SETS, PAGES, attachSink, registerAndLogin, connectDataset, gotoPage, setDark,
  textProblems, headingContrast,
} = require("./helpers.cjs");

const datasets = (process.env.ARIA_AUDIT_SETS || "A,C,B").split(",").map((s) => s.trim());

for (const key of datasets) {
  for (const theme of ["light", "dark"]) {
    test(`dataset ${key} - ${theme} - every page`, async ({ page }, testInfo) => {
      const sink = attachSink(page);
      const creds = await registerAndLogin(page);
      await connectDataset(page, key, creds);
      await setDark(page, theme === "dark");
      const cells = [];
      for (const p of PAGES) {
        const before = { ...sink, pe: sink.pageErrors.length, he: sink.httpErrors.length,
                         ce: sink.consoleErrors.length };
        await test.step(`${p.nav}`, async () => {
          await gotoPage(page, p.nav);
          const problems = await textProblems(page, SETS[key].raw,
            { allowRaw: p.id === "data" });   // the Data page shows the schema itself
          const contrast = await headingContrast(page);
          const lowContrast = contrast.filter((c) => c.ratio < 3);
          if (lowContrast.length) {
            problems.push(`low-contrast headings: ${lowContrast.map((c) => `"${c.text}" ${c.ratio}:1`).join("; ")}`);
          }
          const pageErrors = sink.pageErrors.slice(before.pe);
          const http5xx = sink.httpErrors.slice(before.he).filter((e) => /^5\d\d/.test(e));
          const http4xx = sink.httpErrors.slice(before.he).filter((e) => /^4\d\d/.test(e));
          const consoleErrors = sink.consoleErrors.slice(before.ce);
          await page.screenshot({ path: testInfo.outputPath(`${key}-${theme}-${p.id}.png`) });
          cells.push({ dataset: key, theme, page: p.nav, problems, pageErrors, http5xx, http4xx,
                       consoleErrors });
          expect.soft(pageErrors, `${p.nav}: JavaScript errors`).toEqual([]);
          expect.soft(http5xx, `${p.nav}: server errors`).toEqual([]);
          expect.soft(problems, `${p.nav}: visible-text problems`).toEqual([]);
        });
      }
      await testInfo.attach("cells.json", { body: JSON.stringify(cells, null, 2),
                                            contentType: "application/json" });
    });
  }
}
