/* One plain-English label for every raw identifier shown in the UI.

   Mirrors the backend helper (schema_engine/lexical.py identifier_words +
   ABBREVIATIONS) so a column reads the same on every page and in every
   answer: "txn_dt" -> "Transaction date", "TotalDue" -> "Total due",
   "sales.SalesPerson" -> "Sales person". Generic naming conventions only,
   never schema or business names. */

const ABBREVIATIONS: Record<string, string> = {
  amt: "amount", amnt: "amount", qty: "quantity", qnty: "quantity",
  cnt: "count", avg: "average", tot: "total", val: "value",
  num: "number", nbr: "number", pct: "percent", perc: "percent",
  desc: "description", cat: "category", yr: "year", yrs: "years",
  mth: "month", dt: "date", ts: "timestamp", txn: "transaction",
  trx: "transaction", txns: "transactions", cust: "customer",
  nm: "name", cd: "code", addr: "address", acct: "account",
  mthd: "method", pmt: "payment", pymt: "payment", prod: "product",
  dept: "department", emp: "employee", mgr: "manager", ord: "order",
  qtr: "quarter", wk: "week", disc: "discount", rev: "revenue",
  prc: "price", bal: "balance", loc: "location", curr: "currency",
  ccy: "currency", freq: "frequency", uom: "unit of measure",
  src: "source", dest: "destination", ref: "reference",
};

/** Lowercase words of an identifier: table qualifier dropped, CamelCase and
 *  separators split, data shorthand expanded. */
export function identifierWords(v: unknown): string[] {
  const raw = String(v ?? "").trim().replace(/^["'`[]+|["'`\]]+$/g, "");
  const bare = raw.includes(".") ? raw.slice(raw.lastIndexOf(".") + 1) : raw;
  const spaced = bare
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  const out: string[] = [];
  for (const tok of spaced.split(/[^A-Za-z0-9]+/)) {
    if (!tok) continue;
    const low = tok.toLowerCase();
    out.push(...(ABBREVIATIONS[low] || low).split(" "));
  }
  return out;
}

/** "pay_mthd" -> "Pay method"; titleCase -> "Pay Method". Short all-caps
 *  codes ("SKU", "ID") stay as written. */
export function humanizeLabel(v: unknown, opts: { titleCase?: boolean } = {}): string {
  const raw = String(v ?? "").trim();
  if (!raw) return "";
  const bare = raw.includes(".") ? raw.slice(raw.lastIndexOf(".") + 1) : raw;
  if (/^[A-Z0-9%]+$/.test(bare) && bare.length <= 6) return bare;
  const words = identifierWords(raw);
  if (!words.length) return raw;
  if (opts.titleCase) return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
  const s = words.join(" ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Display name for a connected dataset or database: "dataset_c_messy_txns"
 *  -> "Dataset c messy transactions", "aria_test" -> "Aria test". The raw
 *  name stays the identifier everywhere else (APIs, storage, switching). */
export function datasetLabel(name: unknown): string {
  const raw = String(name ?? "").trim();
  return raw ? humanizeLabel(raw) : "";
}
