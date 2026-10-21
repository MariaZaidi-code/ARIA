/* Screen context for Ask ARIA (the floating bot).

   Pages publish a plain summary of what is on screen right now (the same
   numbers the user sees). When the user asks the bot to explain the screen
   ("I don't understand this dashboard", "what does -1% mean?", "what is
   data quality?"), the answer is built from that summary, so it always
   matches the screen and needs no server round-trip. Data questions
   ("total amount by month", "why did it drop?") return null here and go to
   the backend as before.

   Never invents numbers: every figure comes from the published summary. */

export interface ScreenKpi {
  label: string;
  /** Value exactly as the card shows it ("1.07M"). */
  display: string;
  /** Exact value when known ("1,071,222"), else "". */
  exact: string;
  /** Percent change shown on the card, or null when no change is shown. */
  change: number | null;
  /** What the change compares ("the previous period"), or "". */
  comparedWith: string;
}

export interface ScreenChart {
  title: string;
  subtitle: string;
  kind: "time" | "category" | "other";
  measure: string;
  dim: string;
  /** Time step in lower case ("month"), "" for category charts. */
  grain: string;
  /** Header value as shown ("34.0K"). */
  latest: string;
  change: number | null;
  /** "ARIA found: ..." note under the chart header, or "". */
  note: string;
  peakLabel: string;
  peak: string;
}

export interface ScreenInsight {
  title: string;
  detail: string;
  type: string;
}

export interface ScreenSnapshot {
  page: string;
  dataset: string;
  records: number | null;
  tables: number | null;
  /** Data quality badge (0-100) or null when not shown. */
  quality: number | null;
  /** Share of filled-in values (0-100) behind the quality score, if known. */
  completeness: number | null;
  kpis: ScreenKpi[];
  charts: ScreenChart[];
  insights: ScreenInsight[];
}

export interface ScreenAnswer {
  text: string;
  /** Next questions offered as chips (screen or data questions). */
  followUps: string[];
}

const snapshots: Record<string, ScreenSnapshot> = {};

export function publishScreen(snap: ScreenSnapshot): void {
  snapshots[snap.page] = snap;
}

export function clearScreen(page: string): void {
  delete snapshots[page];
}

export function getScreen(page: string): ScreenSnapshot | null {
  return snapshots[page] || null;
}

/* ---------------- wording helpers ---------------- */

const norm = (s: string) => ` ${String(s || "").toLowerCase().replace(/[^a-z0-9%.\-\s]/g, " ").replace(/\s+/g, " ").trim()} `;

const pct = (n: number) => `${Math.abs(n) % 1 === 0 ? Math.abs(n).toFixed(0) : Math.abs(n).toFixed(1)}%`;

function sizeWords(n: number): string {
  const a = Math.abs(n);
  if (a < 2) return "a small move, usually normal ups and downs";
  if (a < 10) return "a noticeable move worth keeping an eye on";
  return "a big move worth looking into";
}

function changeSentence(k: ScreenKpi): string {
  if (k.change === null) return "";
  const dir = k.change > 0 ? "up" : "down";
  const basis = k.comparedWith || "the previous period";
  return `It is ${dir} ${pct(k.change)} compared with ${basis}: ${sizeWords(k.change)}.`;
}

/** What the number itself means, read from its label. */
function kpiMeaning(label: string): string {
  const l = label.toLowerCase();
  if (/\brecords?\b|\brows?\b/.test(l)) return "how many rows (individual records, such as transactions or orders) your data contains";
  if (/\b(average|avg|mean|typical)\b/.test(l)) return "the typical value for one record: the total divided by the number of records";
  if (/\b(count|number of|distinct|unique)\b/.test(l)) {
    const what = l.replace(/\b(count|number of|distinct|unique)\b/g, "").trim();
    return `how many different ${what || "items"} appear in your data`;
  }
  if (/\b(total|sum|revenue|sales|amount|due|value)\b/.test(l)) return "everything added together across all records";
  if (/\b(rate|ratio|share|%|percent)\b/.test(l)) return "a share, shown as a percentage";
  return "one of the key numbers ARIA picked from your data";
}

function kpiAnswer(k: ScreenKpi): ScreenAnswer {
  const exact = k.exact && k.exact !== k.display ? ` (exactly ${k.exact})` : "";
  const lines = [
    `${k.label} is ${k.display}${exact}.`,
    `It shows ${kpiMeaning(k.label)}.`,
  ];
  const ch = changeSentence(k);
  if (ch) lines.push(ch);
  lines.push("Select the card to analyse it, or use \"Ask about this\" under the number.");
  return {
    text: lines.join(" "),
    followUps: [
      ...(k.change !== null ? [`Why did ${k.label.toLowerCase()} change?`] : []),
      `How has ${k.label.toLowerCase()} changed over time?`,
      "Explain this dashboard",
    ],
  };
}

function chartAnswer(c: ScreenChart): ScreenAnswer {
  const lines: string[] = [];
  if (c.kind === "time") {
    lines.push(`"${c.title}" shows ${c.measure.toLowerCase()} for each ${c.grain || "period"}${c.subtitle ? ` (${c.subtitle})` : ""}.`);
    if (c.latest) {
      lines.push(`The number in the header, ${c.latest}, is the latest ${c.grain || "period"}`
        + (c.change !== null
          ? `, ${c.change >= 0 ? "up" : "down"} ${pct(c.change)} compared with the ${c.grain || "period"} before.`
          : "."));
    }
    if (c.peakLabel && c.peak) lines.push(`The highest point was ${c.peakLabel} at ${c.peak}.`);
  } else if (c.kind === "category") {
    lines.push(`"${c.title}" ranks each ${c.dim.toLowerCase() || "group"} by ${c.measure.toLowerCase()}, largest first.`);
    if (c.peakLabel) lines.push(`${c.peakLabel} leads${c.latest ? ` with ${c.latest}` : ""}.`);
  } else {
    lines.push(`"${c.title}" ${c.subtitle ? `shows ${c.subtitle}` : "is one of the key charts for your data"}.`);
  }
  if (c.note) lines.push(`ARIA's note under the header: ${c.note}`);
  lines.push("Point at the chart to see each value; select a point to dig into it.");
  return {
    text: lines.join(" "),
    followUps: [
      c.kind === "time" ? `Why did ${c.measure.toLowerCase()} change?` : `Compare ${c.measure.toLowerCase()} across ${c.dim.toLowerCase() || "groups"}`,
      "What does the percentage on a chart mean?",
      "Explain this dashboard",
    ],
  };
}

function overviewAnswer(s: ScreenSnapshot): ScreenAnswer {
  const lines: string[] = [];
  const scope = [
    s.records !== null ? `${s.records.toLocaleString()} records` : "",
    s.tables !== null ? `${s.tables} ${s.tables === 1 ? "table" : "tables"}` : "",
  ].filter(Boolean).join(" in ");
  lines.push(`This is your Dashboard: a one-page summary of ${s.dataset || "your connected data"}${scope ? ` (${scope})` : ""}.`);
  if (s.kpis.length) {
    lines.push("");
    lines.push("The cards at the top are your key numbers:");
    for (const k of s.kpis) {
      const ch = k.change !== null ? `, ${k.change >= 0 ? "up" : "down"} ${pct(k.change)} vs ${k.comparedWith || "the previous period"}` : "";
      lines.push(`• ${k.label}: ${k.display}${ch}`);
    }
  }
  if (s.charts.length) {
    lines.push("");
    lines.push(`Below them, ${s.charts.length === 1 ? "a chart shows" : "charts show"} ${s.charts.map((c) => `"${c.title}"`).join(" and ")}.`);
  }
  if (s.insights.length) {
    lines.push("");
    lines.push(`On the right, "Recent Insights" lists what ARIA spotted, starting with: ${s.insights[0].title}.`);
  }
  if (s.quality !== null) {
    lines.push("");
    lines.push(`The "Data quality ${s.quality}%" badge tells you how complete and well-formed the data is.`);
  }
  lines.push("");
  lines.push("Ask me about any card, chart or word you don't understand.");
  const first = s.kpis.find((k) => k.change !== null) || s.kpis[0];
  return {
    text: lines.join("\n"),
    followUps: [
      ...(first ? [`What does ${first.label} mean?`] : []),
      ...(s.insights.length ? ["What did ARIA find?"] : []),
      ...(s.quality !== null ? ["What is data quality?"] : []),
    ].slice(0, 3),
  };
}

function insightsAnswer(s: ScreenSnapshot): ScreenAnswer | null {
  if (!s.insights.length) return null;
  const top = s.insights.slice(0, 3);
  const lines = ["Here is what ARIA spotted in your data:"];
  for (const i of top) {
    lines.push(`• ${i.title}${i.detail ? `: ${i.detail}` : ""}`);
  }
  lines.push("");
  lines.push("Each one has \"Ask ARIA\" next to it if you want the details explained.");
  return { text: lines.join("\n"), followUps: [`Explain this finding: ${top[0].title}`, "Explain this dashboard"] };
}

/* Glossary of words on the Dashboard. Each entry answers with the
   on-screen figure when there is one. */
type Term = { re: RegExp; answer: (s: ScreenSnapshot) => ScreenAnswer | null };

const TERMS: Term[] = [
  {
    re: /\bdata quality\b|\bquality (score|badge|%)/,
    answer: (s) => {
      if (s.quality === null) return { text: "Data quality shows how complete and well-formed your data is. It appears once ARIA has scanned your data.", followUps: [] };
      const comp = s.completeness !== null ? ` About ${pct(s.completeness)} of the values are filled in.` : "";
      const verdict = s.quality >= 95 ? "That is very good: you can trust the numbers on this page."
        : s.quality >= 80 ? "That is fine, but some values are missing, so a few totals may be slightly low."
        : "That is low: many values are missing, so check the Data page before relying on these numbers.";
      return {
        text: `Data quality ${s.quality}% measures how complete and well-formed your data is: mostly how many values are filled in, plus whether tables have ID columns and actually contain rows.${comp} ${verdict}`,
        followUps: ["Explain this dashboard"],
      };
    },
  },
  {
    re: /previous period|compared with/,
    answer: (s) => {
      const k = s.kpis.find((x) => x.change !== null);
      const ex = k ? ` For example, ${k.label} is ${k.change! >= 0 ? "up" : "down"} ${pct(k.change!)}.` : "";
      return {
        text: `"Compared with previous period" means the latest period (for example the latest month) is compared with the one just before it. The percentage is how much it grew or shrank.${ex}`,
        followUps: k ? [`Why did ${k.label.toLowerCase()} change?`] : [],
      };
    },
  },
  {
    re: /\b(percent|percentage|arrows?|red|green)\b|%/,
    answer: (s) => {
      const k = s.kpis.find((x) => x.change !== null);
      const ex = k ? ` On your screen, ${k.label} shows ${k.change! >= 0 ? "↗" : "↘"} ${pct(k.change!)}: ${sizeWords(k.change!)}.` : "";
      return {
        text: `The arrow and percentage show change. Green ↗ means the number went up, red ↘ means it went down, compared with the previous period. Under 2% is usually normal variation; over 10% is a big move.${ex}`,
        followUps: k ? [`Why did ${k.label.toLowerCase()} change?`] : [],
      };
    },
  },
  {
    re: /\b\d+(\.\d+)?\s?[km]\b|\bwhat (do|does) (k|m) mean\b|\bthousand|\bmillion/,
    answer: () => ({
      text: "K means thousand and M means million, so 34.0K is about 34,000 and 1.07M is about 1,070,000. Point at a number or chart to see the exact value.",
      followUps: [],
    }),
  },
  {
    re: /\banomal/,
    answer: (s) => {
      const a = s.insights.find((i) => /anomal/i.test(i.type) || /anomal/i.test(i.title));
      return {
        text: `An anomaly is a value that is unusually high or low compared with the rest of your data, worth checking because it may be a mistake or a real event.${a ? ` ARIA flagged: ${a.title}.` : ""}`,
        followUps: a ? [`Explain this finding: ${a.title}`] : [],
      };
    },
  },
  {
    re: /\b(opportunit|risk|insight)/,
    answer: (s) => ({
      text: `Insights are things ARIA noticed in your data. An "Opportunity" is something that could be grown, a "Risk" is something that could hurt results, and "Performance" describes how a number moved.${s.insights.length ? ` The first one on your screen: ${s.insights[0].title}.` : ""}`,
      followUps: s.insights.length ? ["What did ARIA find?"] : [],
    }),
  },
  {
    re: /small (line|chart)|sparkline|mini (chart|graph)|wavy line/,
    answer: () => ({
      text: "The small line on a card is a mini chart of that number over time, so you can see its recent shape at a glance. It has no axis; select the card for the full chart.",
      followUps: [],
    }),
  },
  {
    re: /ask about this|why did this move|add to report/,
    answer: () => ({
      text: "Under each card: \"Ask about this\" sends that number to ARIA for an explanation, \"Why did this move?\" looks for the reasons behind the change, and \"Add to report\" saves the card into a report you can export.",
      followUps: [],
    }),
  },
  {
    re: /last (6|12|six|twelve)|\ball\b.*\b(button|filter|range)|range buttons?/,
    answer: () => ({
      text: "\"All\", \"Last 12\" and \"Last 6\" change how many periods the charts show. They only zoom the view; the totals on the cards stay the same.",
      followUps: [],
    }),
  },
];

/* ---------------- intent ---------------- */

const OVERVIEW = /\b(this|the|my) (page|screen|dashboard)\b|what am i looking at|i (do ?n.?t|dont|do not|can.?t|cannot) (understand|get|follow)|confus|help me (understand|read)|how (do i|to|should i) (read|use|understand)|explain (it|everything|all of this|all this)\b|\bdashboard\b/;
const EXPLAIN = /\b(what does|what do|what is|what's|whats|what are|meaning|mean|means|explain|understand|tell me about|is (this|that|it) (good|bad|normal|ok)|should i (worry|be worried)|how (do|should) i read)\b|^ (is|are) .*\b(good|bad|normal|ok|okay|healthy|worrying)\b/;
/* Analysis wording goes to the backend: it needs a query, not the screen. */
const ANALYSIS = /\b(by|per|each|top|bottom|highest|lowest|rank|ranking|compare|forecast|predict|list|break ?down|why|which|over time|trend of|filter)\b/;
const THING = /\b(card|chart|graph|number|kpi|metric|figure|value|this|that|it)\b/;

function findKpi(q: string, s: ScreenSnapshot): ScreenKpi | null {
  const hits = s.kpis
    .filter((k) => { const l = norm(k.label).trim(); return l && q.includes(` ${l} `); })
    .sort((a, b) => b.label.length - a.label.length);
  return hits[0] || null;
}

function findChart(q: string, s: ScreenSnapshot): ScreenChart | null {
  if (!s.charts.length) return null;
  if (/\b(first|top|left) (chart|graph)\b/.test(q)) return s.charts[0];
  if (/\b(second|right|other) (chart|graph)\b/.test(q)) return s.charts[1] || null;
  const titled = s.charts.find((c) => { const t = norm(c.title).trim(); return t && q.includes(` ${t} `); });
  if (titled) return titled;
  if (/\b(chart|graph)\b/.test(q)) return s.charts[0];
  return null;
}

/** Answer a question about what is on screen, or null to let the backend
 *  answer it (data questions, or nothing on screen to explain). */
export function explainScreen(question: string, s: ScreenSnapshot | null): ScreenAnswer | null {
  if (!s) return null;
  const q = norm(question);
  if (!q.trim()) return null;
  const explain = EXPLAIN.test(q);
  // Names on screen can contain analysis words ("Amount by Month"), so
  // they are removed before deciding whether the question needs a query.
  // Chart titles only count as names when the question is about a chart:
  // "total amount by month?" is a data question, not the chart's title.
  let rest = q;
  const names = [...(/\b(chart|graph)\b/.test(q) ? s.charts.map((c) => c.title) : []), ...s.kpis.map((k) => k.label)];
  for (const name of names) {
    const n = norm(name).trim();
    if (n) rest = rest.split(` ${n} `).join(" ");
  }
  const analysis = ANALYSIS.test(rest);

  // "Explain this finding: ..." chips and "why" questions are analysis.
  if (/^ explain this finding/.test(q)) return null;

  if (/what did aria (find|notice|spot)|recent insights|(explain|show|what are) (the |my )?(insights|findings)/.test(q)) {
    const a = insightsAnswer(s);
    if (a) return a;
  }

  // Words on the screen ("data quality", "%", "previous period", ...).
  if ((explain || /\?\s*$/.test(question.trim()) || THING.test(q)) && !(analysis && !explain)) {
    for (const t of TERMS) {
      if (t.re.test(q)) {
        const a = t.answer(s);
        if (a) return a;
      }
    }
  }

  // A specific card or chart, explained. Analysis wording ("... by month",
  // "top ...") needs a query, so it goes to the backend instead. A plain
  // "what is the total amount?" is a data question too: the engine answers
  // it with the exact value and "How I got this".
  if (!analysis) {
    const k = findKpi(q, s);
    const wantsMeaning = /\b(mean|means|meaning|explain|understand|tell me about|what does|what do)\b/.test(q)
      || /^ (is|are) .*\b(good|bad|normal|ok|okay|healthy|worrying)\b/.test(q)
      || /\b(card|kpi|figure)\b/.test(q);
    if (k && wantsMeaning) return kpiAnswer(k);
    const c = findChart(q, s);
    if (c && (explain || /\b(chart|graph)\b/.test(q))) return chartAnswer(c);
  }

  // The page as a whole.
  if (OVERVIEW.test(q) && (explain || !analysis)) return overviewAnswer(s);

  return null;
}

/** Starter chips for the bot on this screen (before any question). */
export function screenStarters(s: ScreenSnapshot | null): string[] {
  if (!s || (!s.kpis.length && !s.charts.length)) return [];
  const k = s.kpis.find((x) => x.change !== null) || s.kpis[0];
  return [
    "Explain this dashboard",
    ...(k ? [`What does ${k.label} mean?`] : []),
    ...(s.quality !== null ? ["What is data quality?"] : s.insights.length ? ["What did ARIA find?"] : []),
  ];
}
