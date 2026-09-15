import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import {
  BarChart3, Lightbulb, Target, SlidersHorizontal, FileText, Play, RotateCcw,
  Bookmark, ChevronRight, ArrowLeft, RefreshCw, AlertTriangle, Database,
  Sparkles, Send, FlaskConical, Compass, Plus, Printer, Download, Share2,
  CalendarDays, Save, Eye, X, ArrowUpRight, ArrowDownRight, Check,
} from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell,
} from "recharts";
import { useTheme } from "../App";
import { colorForName } from "../lib/charts";
import { fmtBiz, fmtMoneyBiz, fmtPctBiz } from "../lib/format";
import { intelligenceApi, normalizeApiError, apiFetch } from "../../services/api";

/* =====================================================================
   ARIA Intelligence — Explore / Hypotheses / Goals / What-If / Reports.
   Single page with an icon tab bar (Explore, Hypotheses, Goals, What-If,
   Reports). Every number, label option, status and range comes from
   GET/POST /api/intelligence/* — the frontend formats and renders but
   never calculates truth (no confidence/priority/impact math in React).
   No values are hardcoded from design screenshots.
   ===================================================================== */

type IntelTab = "explore" | "hypotheses" | "goals" | "whatif" | "reports";

const TABS: { id: IntelTab; label: string; Icon: typeof BarChart3 }[] = [
  { id: "explore", label: "Explore", Icon: BarChart3 },
  { id: "hypotheses", label: "Hypotheses", Icon: Lightbulb },
  { id: "goals", label: "Goals", Icon: Target },
  { id: "whatif", label: "What-If", Icon: SlidersHorizontal },
  { id: "reports", label: "Reports", Icon: FileText },
];

function tabFromHash(): IntelTab {
  try {
    const m = /[?&]tab=([a-z]+)/.exec(window.location.hash || "");
    const t = (m?.[1] || "").toLowerCase();
    if (t === "hypotheses" || t === "goals" || t === "whatif" || t === "what-if" || t === "reports" || t === "explore") {
      return t === "what-if" ? "whatif" : (t as IntelTab);
    }
  } catch { /* ignore */ }
  return "explore";
}

/* ---------- small shared helpers (presentation only) ---------- */

/* Human-scale metric formatting: money-like metrics get $, others plain.
   Prevents raw long decimals and misleading $ on counts. */
function isMoneyMetric(name: unknown): boolean {
  const s = String(name || "").toLowerCase();
  return /(revenue|sales|price|cost|profit|amount|total|payment|spend|budget|discount|wage|salary|fee|fare|freight|tuition|premium|margin)/.test(s);
}
function fmtMetric(v: number | null | undefined, metricName?: unknown): string {
  if (v === null || v === undefined) return "\u2014";
  return isMoneyMetric(metricName) ? fmtMoneyBiz(v) : fmtBiz(v);
}

function goData() {
  try { window.location.hash = "#/data"; } catch { /* ignore */ }
}

function NoDatasetPanel({ onRetry }: { onRetry?: () => void }) {
  return (
    <div className="text-center py-10 bg-white border border-slate-200 rounded-2xl shadow-sm px-6">
      <Database size={22} className="mx-auto text-slate-400 mb-3" />
      <p className="text-sm font-medium text-[#0F2440]">No data source connected</p>
      <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">Connect PostgreSQL, MySQL, or upload a CSV on the Data page — then every section here will populate and Run Analysis will generate results.</p>
      <div className="mt-3 flex items-center justify-center gap-2">
        <button onClick={goData} className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12.5px] font-semibold text-white bg-blue-700 hover:bg-blue-800" aria-label="Go to Data page">Go to Data</button>
        {onRetry && <button onClick={onRetry} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:border-slate-300 bg-white" aria-label="Retry loading options"><RefreshCw size={12} /> Retry</button>}
      </div>
    </div>
  );
}

function humanize(v: unknown): string {
  const s = String(v ?? "").trim();
  if (!s) return "";
  const spaced = s.replace(/[_-]+/g, " ").replace(/([a-z0-9])([A-Z])/g, "$1 $2").replace(/\s+/g, " ").trim();
  if (/^[A-Z0-9_()%. ]+$/.test(s) && s.length <= 10) return s.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/* Business-worded error copy: never a bare "Failed to fetch", never SQL. */
function businessError(raw: string): string {
  const s = String(raw || "");
  if (!s) return "";
  if (/failed to fetch|network|load failed|request failed|fetch|backend unreachable|timed out|timeout/i.test(s)) {
    return "ARIA couldn't reach the server for this Intelligence request. Check that the backend is running, then retry.";
  }
  if (/session expired|sign in|unauthorized|401/i.test(s)) return s.slice(0, 200);
  if (/select\s.+\sfrom|traceback|exception|stack/i.test(s)) {
    return "ARIA couldn't complete this Intelligence request. Try again in a moment.";
  }
  return s.slice(0, 220);
}

const asList = (v: unknown): any[] => (Array.isArray(v) ? v : []);
const strOf = (v: unknown, fb = ""): string => (typeof v === "string" ? v : v === null || v === undefined ? fb : String(v));
const numOf = (v: unknown): number | null => {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(String(v).replace(/,/g, ""));
  return isNaN(n) ? null : n;
};

/* Associated-factor guard: the frontend must never display
   "schema-discovered lever" rows or FK-as-driver rows, even if a backend
   ever sent them. */
function isValidFactor(f: any): boolean {
  const hay = [f?.factor, f?.name, f?.label, f?.type, f?.kind, f?.role, f?.relationship, f?.association]
    .map((x) => String(x || "").toLowerCase()).join(" | ");
  if (/schema-discovered lever|schema_discovered_lever|schema lever/.test(hay)) return false;
  const kind = String(f?.type || f?.kind || f?.role || "").toLowerCase().replace(/[\s_]+/g, "");
  if (["foreignkey", "fk", "joinkey", "joincolumn"].includes(kind)) return false;
  if (/foreign key as driver|fk as driver|fk-as-driver/.test(hay)) return false;
  return true;
}

/* ---------- shared UI atoms ---------- */

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white border border-slate-200/80 rounded-2xl shadow-[0_1px_2px_rgba(15,36,64,0.05)] ${className}`}>
      {children}
    </div>
  );
}

function CardHead({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 flex-wrap px-4 pt-4 md:px-5">
      <div className="min-w-0">
        <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">{title}</h3>
        {sub && <p className="text-[11px] text-slate-500 mt-0.5">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

function SkeletonBlock({ lines = 3, className = "" }: { lines?: number; className?: string }) {
  return (
    <div className={`p-4 space-y-2 ${className}`} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton h-3.5 rounded" style={{ width: `${92 - i * 14}%` }} />
      ))}
      <div className="skeleton h-28 rounded-xl" />
    </div>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <div aria-busy="true" aria-label={label}>
      <p className="sr-only">{label}</p>
      <Card><SkeletonBlock lines={3} /></Card>
    </div>
  );
}

function ErrorPanel({ message, requestId, onRetry, retryLabel = "Retry" }: {
  message: string; requestId?: string; onRetry: () => void; retryLabel?: string;
}) {
  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-5 flex gap-3 shadow-sm" role="alert">
      <AlertTriangle size={18} className="text-rose-500 flex-shrink-0 mt-0.5" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-[#0F2440]">ARIA couldn&apos;t load this section.</p>
        <p className="text-xs text-slate-500 mt-1">{businessError(message) || "Something went wrong on this request."}</p>
        {requestId && <p className="text-[11px] text-slate-400 mt-1 font-mono">Request ID: {requestId}</p>}
        <button onClick={onRetry} className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 hover:underline">
          <RefreshCw size={12} /> {retryLabel}
        </button>
      </div>
    </div>
  );
}

function EmptyPanel({ icon: Icon, title, body, action }: {
  icon?: typeof Sparkles; title: string; body: string; action?: React.ReactNode;
}) {
  const I = Icon || Sparkles;
  return (
    <div className="text-center py-10 bg-white border border-slate-200 rounded-2xl shadow-sm px-6">
      <I size={22} className="mx-auto text-slate-400 mb-3" />
      <p className="text-sm font-medium text-[#0F2440]">{title}</p>
      <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">{body}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

function Field({ label, children, htmlFor }: { label: string; children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="block min-w-0">
      <span className="block text-[11px] font-medium text-slate-500 mb-1">{label}</span>
      {children}
    </label>
  );
}

const selectCls = "w-full bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-[12.5px] text-[#0F2440] focus:border-blue-500 outline-none cursor-pointer min-w-0";
const inputCls = "w-full bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-[12.5px] text-[#0F2440] placeholder:text-slate-400 focus:border-blue-500 outline-none min-w-0";
const btnPrimary = "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-[12.5px] font-semibold text-white bg-blue-700 hover:bg-blue-800 disabled:opacity-50 transition-colors";
const btnGhost = "inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:text-[#0F2440] hover:border-slate-300 bg-white transition-colors";

/* =====================================================================
   EXPLORE — Intelligence Home + Analysis Workspace merged
   ===================================================================== */

const QUICK_ACTIONS = [
  { id: "metric", label: "Explore a Metric", sub: "Analyze any metric", Icon: BarChart3 },
  { id: "segments", label: "Compare Segments", sub: "Compare performance", Icon: Compass },
  { id: "change", label: "Investigate a Change", sub: "Understand what changed", Icon: FlaskConical },
  { id: "anomaly", label: "Find Anomalies", sub: "Discover unusual patterns", Icon: AlertTriangle },
  { id: "trend", label: "Analyze a Trend", sub: "View trends over time", Icon: BarChart3 },
  { id: "compare", label: "Build a Comparison", sub: "Side-by-side analysis", Icon: Compass },
  { id: "goal", label: "Create a Goal", sub: "Track a business target", Icon: Target },
  { id: "scenario", label: "Run a Scenario", sub: "Test a what-if scenario", Icon: SlidersHorizontal },
] as const;

interface ExploreProps {
  meta: any;
  onRunQuick: (actionId: string) => void;
  onGoto: (t: IntelTab) => void;
  onAsk: (q: string) => void;
}

function ExploreTab({ meta, onRunQuick, onGoto, onAsk }: ExploreProps) {
  const optOf = (x: any): { value: string; label: string } => {
    if (typeof x === "string") return { value: x, label: humanize(x) };
    const value = strOf(x?.column || x?.name || x?.label);
    const label = strOf(x?.label || x?.name ? humanize(strOf(x?.label || x?.name)) : humanize(value));
    return { value, label };
  };
  const metrics: { value: string; label: string }[] = useMemo(() => {
    const m = meta?.metrics ?? meta?.measures ?? [];
    return asList(m).map(optOf).filter((o) => o.value);
  }, [meta]);
  const breakdowns: { value: string; label: string }[] = useMemo(() => {
    const b = meta?.breakdowns ?? meta?.dimensions ?? [];
    return asList(b).map(optOf).filter((o) => o.value);
  }, [meta]);
  const grains: string[] = useMemo(() => asList(meta?.time_grains ?? meta?.timeGrains ?? ["Monthly"]).map((x) => strOf(x)).filter(Boolean), [meta]);
  const comparisons: string[] = useMemo(() => asList(meta?.comparisons ?? ["Previous Period"]).map((x) => strOf(typeof x === "string" ? x : x?.name || x?.label)).filter(Boolean), [meta]);
  const dateRanges: string[] = useMemo(() => asList(meta?.date_ranges ?? meta?.dateRanges ?? ["Last 12 months"]).map((x) => strOf(typeof x === "string" ? x : x?.name || x?.label)).filter(Boolean), [meta]);
  const filterCols: { value: string; label: string }[] = useMemo(() => {
    const c = meta?.filterable_columns ?? meta?.filterColumns ?? breakdowns;
    return asList(c).map(optOf).filter((o) => o.value);
  }, [meta, breakdowns]);

  const [metric, setMetric] = useState("");
  const [breakdown, setBreakdown] = useState("");
  const [grain, setGrain] = useState("");
  const [comparison, setComparison] = useState("");
  const [dateRange, setDateRange] = useState("");
  const [secondary, setSecondary] = useState("");
  const [showSecondary, setShowSecondary] = useState(false);
  const [filters, setFilters] = useState<{ column: string; value: string }[]>([]);
  const [filterCol, setFilterCol] = useState("");
  const [filterVal, setFilterVal] = useState("");
  const [chartMode, setChartMode] = useState<"bar" | "line">("bar");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [errorId, setErrorId] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");
  const [recent, setRecent] = useState<any[]>([]);
  const [savedCols, setSavedCols] = useState<any[]>([]);
  const [homeQuery, setHomeQuery] = useState("");
  const [showFilterRow, setShowFilterRow] = useState(false);
  const [showAllRecent, setShowAllRecent] = useState(false);
  const [showAllSaved, setShowAllSaved] = useState(false);

  const HOME_SUGGESTIONS = [
    "Why did revenue change?",
    "Compare sales across regions",
    "Which products are declining?",
    "Show me customer growth",
    "Find unusual changes in orders",
  ];

  const relativeOpened = (iso: string): string => {
    if (!iso) return "";
    try {
      const d = new Date(iso);
      const now = new Date();
      const sameDay = d.toDateString() === now.toDateString();
      const yest = new Date(now);
      yest.setDate(now.getDate() - 1);
      const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
      if (sameDay) return `Opened today, ${time}`;
      if (d.toDateString() === yest.toDateString()) return `Opened yesterday, ${time}`;
      return `Opened ${d.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })}`;
    } catch { return strOf(iso); }
  };

  const savedBuckets = (() => {
    const map = new Map<string, any[]>();
    for (const a of savedCols) {
      const key = strOf(a?.metric ? humanize(strOf(a.metric)) : a?.collection ? strOf(a.collection) : a?.title ? strOf(a.title).split(" by ")[0] : "General");
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(a);
    }
    return Array.from(map.entries()).map(([name, items]) => ({ name, count: items.length, items }));
  })();

  const submitHomeQuery = () => {
    const q = homeQuery.trim();
    if (!q) { runAnalysis(); return; }
    onAsk(q);
    setTimeout(() => runAnalysis(), 120);
  };
  const runAbort = useRef<AbortController | null>(null);

  /* Preselect first backend options once meta arrives — never invented. */
  useEffect(() => {
    if (!metric && metrics.length) setMetric(metrics[0].value);
    if (!breakdown && breakdowns.length) setBreakdown(breakdowns[0].value);
    if (!grain && grains.length) setGrain(grains[0]);
    if (!comparison && comparisons.length) setComparison(comparisons[0]);
    if (!dateRange && dateRanges.length) setDateRange(dateRanges[0]);
    if (!filterCol && filterCols.length) setFilterCol(filterCols[0].value);
  }, [metrics, breakdowns, grains, comparisons, dateRanges, filterCols, metric, breakdown, grain, comparison, dateRange, filterCol]);

  const loadRecent = useCallback(async () => {
    try {
      const r = await intelligenceApi.listAnalyses({ page: 1, page_size: 6, sort: "recent" });
      const items = asList(r.data);
      setRecent(items.filter((a) => !a?.saved && !a?.collection));
      setSavedCols(items.filter((a) => a?.saved || a?.collection));
    } catch { /* non-fatal: home cards simply stay empty */ }
  }, []);
  useEffect(() => { loadRecent(); }, [loadRecent]);

  const payload = useMemo(() => ({
    metric: metric || undefined,
    breakdown: breakdown || undefined,
    secondary_breakdown: showSecondary && secondary ? secondary : undefined,
    time_grain: grain || undefined,
    comparison: comparison || undefined,
    date_range: dateRange || undefined,
    filters: filters.filter((f) => f.column && f.value),
  }), [metric, breakdown, secondary, showSecondary, grain, comparison, dateRange, filters]);

  const runAnalysis = useCallback(async (override?: Record<string, unknown>) => {
    runAbort.current?.abort();
    const ctrl = new AbortController();
    runAbort.current = ctrl;
    setRunning(true);
    setError("");
    setErrorId("");
    setSaveMsg("");
    try {
      const r = await intelligenceApi.runExplore({ ...payload, ...(override || {}) });
      if (ctrl.signal.aborted) return;
      setResult(r.data || null);
    } catch (e: any) {
      if (e?.name === "AbortError" || ctrl.signal.aborted) return;
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setError(norm.message);
      setErrorId(norm.requestId);
      setResult(null);
    } finally {
      if (runAbort.current === ctrl) setRunning(false);
    }
  }, [payload]);

  useEffect(() => () => runAbort.current?.abort(), []);

  const quickRun = (actionId: string) => {
    onRunQuick(actionId);
    if (actionId === "goal") { onGoto("goals"); return; }
    if (actionId === "scenario") { onGoto("whatif"); return; }
    if (actionId === "compare" && comparisons.length > 1) setComparison(comparisons[1]);
    if (actionId === "trend" && grains.length) setGrain(grains[0]);
    setTimeout(() => runAnalysis(), 60);
  };

  const reset = () => {
    setSecondary("");
    setShowSecondary(false);
    setFilters([]);
    setFilterVal("");
    setResult(null);
    setError("");
    setErrorId("");
    setSaveMsg("");
    if (metrics.length) setMetric(metrics[0].value);
    if (breakdowns.length) setBreakdown(breakdowns[0].value);
    if (grains.length) setGrain(grains[0]);
    if (comparisons.length) setComparison(comparisons[0]);
    if (dateRanges.length) setDateRange(dateRanges[0]);
  };

  const loadSavedAnalysis = async (a: any) => {
    const resolveOpt = (opts: { value: string; label: string }[], v: string): string => {
      const s = strOf(v);
      if (!s) return "";
      const hit = opts.find((o) => o.value === s || o.label === s || o.value.toLowerCase() === s.toLowerCase() || o.label.toLowerCase() === s.toLowerCase());
      return hit ? hit.value : s;
    };
    const m = resolveOpt(metrics, strOf(a?.metric));
    const b = resolveOpt(breakdowns, strOf(a?.breakdown));
    if (m) setMetric(m);
    if (b) setBreakdown(b);
    if (strOf(a?.time_grain)) setGrain(strOf(a.time_grain));
    if (strOf(a?.comparison)) setComparison(strOf(a.comparison));
    if (strOf(a?.date_range)) setDateRange(strOf(a.date_range));
    setTimeout(() => runAnalysis(), 120);
  };

  const deleteSavedAnalysis = async (id: string) => {
    if (!id) return;
    try {
      await intelligenceApi.deleteAnalysis(id);
      loadRecent();
    } catch (e: any) {
      setSaveMsg(businessError(e?.message) || "ARIA couldn't delete this analysis.");
    }
  };

  const saveAnalysis = async () => {
    if (!result) return;
    setSaving(true);
    setSaveMsg("");
    try {
      await intelligenceApi.saveAnalysis({ ...payload, result_summary: result?.observation?.summary || result?.summary || "" });
      setSaveMsg("Analysis saved. Find it under Recent Analyses.");
      loadRecent();
    } catch (e: any) {
      setSaveMsg(businessError(e?.message) || "ARIA couldn't save this analysis.");
    } finally {
      setSaving(false);
    }
  };

  /* ---- result normalization (backend keys, defensive) ---- */
  const trendPoints = useMemo(() => {
    const raw = asList(result?.trend?.points || result?.trend || result?.series || result?.points || result?.chart?.data);
    return raw.slice(0, 60).map((p: any, i: number) => ({
      label: strOf(p?.label || p?.period || p?.x || p?.month || `P${i + 1}`),
      current: numOf(p?.current ?? p?.current_value ?? p?.value ?? p?.y) ?? 0,
      previous: numOf(p?.previous ?? p?.previous_value ?? p?.prev),
    }));
  }, [result]);
  const trendTitle = strOf(result?.trend?.title || result?.title || (metric && breakdown ? `${humanize(metric)} Trend by ${humanize(breakdown)}` : "Trend"), "Trend");
  const trendSub = strOf(result?.trend?.subtitle || result?.subtitle || "");
  const observation = result?.observation || result?.aria_observation || null;
  const obsSummary = strOf(typeof observation === "string" ? observation : observation?.summary || observation?.text || result?.summary || "");
  const obsBullets: string[] = asList(typeof observation === "object" ? observation?.bullets || observation?.points || observation?.details : []).map((b) => strOf(typeof b === "string" ? b : b?.text || b?.label)).filter(Boolean).slice(0, 8);
  const obsBasis = strOf(observation?.basis_note || observation?.basis || result?.basis_note || "");
  const rows = useMemo(() => asList(result?.breakdown || result?.breakdown_rows || result?.rows || result?.table), [result]);
  const breakdownTitle = strOf(result?.breakdown_title || (breakdown ? `${humanize(breakdown)} Breakdown` : "Breakdown"), "Breakdown");

  const nextSteps = [
    { label: "Investigate this pattern", sub: "Explore possible factors", tab: "hypotheses" as IntelTab, Icon: FlaskConical },
    { label: "Test a scenario", sub: "See what might happen", tab: "whatif" as IntelTab, Icon: SlidersHorizontal },
    { label: "Compare with a goal", sub: "Check against your targets", tab: "goals" as IntelTab, Icon: Target },
    { label: "Create a report", sub: "Turn this analysis into a report", tab: "reports" as IntelTab, Icon: FileText },
  ];

  const hasDataset = metrics.length > 0;
  if (!hasDataset) {
    return (
      <div className="space-y-4">
        <NoDatasetPanel />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <Card className="p-4 md:p-5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
              <Sparkles size={14} className="text-blue-700" /> Build Your Analysis
            </h3>
            <p className="text-[11px] text-slate-500 mt-0.5">Select what you want to analyze. ARIA will calculate and visualize the results from your data.</p>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={saveAnalysis} disabled={!result || saving} className={btnGhost} aria-label="Save analysis">
              <Bookmark size={13} /> {saving ? "Saving…" : "Save Analysis"}
            </button>
            <button onClick={reset} className={btnGhost} aria-label="Reset analysis builder">
              <RotateCcw size={13} /> Reset
            </button>
          </div>
        </div>
        {saveMsg && <p className="mt-2 text-[11px] text-slate-600" role="status">{saveMsg}</p>}

        <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 items-end">
          <Field label="Metric" htmlFor="intel-metric">
            <select id="intel-metric" value={metric} onChange={(e) => setMetric(e.target.value)} className={selectCls} aria-label="Metric">
              {metrics.length === 0 && <option value="">No metrics available</option>}
              {metrics.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select>
          </Field>
          <Field label="Break down by" htmlFor="intel-breakdown">
            <select id="intel-breakdown" value={breakdown} onChange={(e) => setBreakdown(e.target.value)} className={selectCls} aria-label="Break down by">
              <option value="">Overall (no breakdown)</option>
              {breakdowns.map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
            </select>
          </Field>
          <Field label="Time" htmlFor="intel-time">
            <select id="intel-time" value={grain} onChange={(e) => setGrain(e.target.value)} className={selectCls} aria-label="Time granularity">
              {grains.map((g) => <option key={g} value={g}>{humanize(g)}</option>)}
            </select>
          </Field>
          <Field label="Compare" htmlFor="intel-compare">
            <select id="intel-compare" value={comparison} onChange={(e) => setComparison(e.target.value)} className={selectCls} aria-label="Comparison">
              {comparisons.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
            </select>
          </Field>
          <div className="min-w-0">
            <span className="hidden lg:block text-[11px] font-medium text-transparent mb-1 select-none">Run</span>
            <button onClick={() => runAnalysis()} disabled={running || !metric} className={`${btnPrimary} w-full !h-[40px]`} aria-label="Run analysis">
              {running ? "Running..." : "Run Analysis"} <Play size={13} />
            </button>
          </div>
        </div>

        <div className="mt-3 flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-3">
          {!showSecondary ? (
            <button onClick={() => setShowSecondary(true)} className="text-[12px] font-medium text-blue-700 hover:underline" aria-label="Add secondary breakdown">
              + Add secondary breakdown
            </button>
          ) : (
            <div className="flex items-center gap-2 min-w-0">
              <select value={secondary} onChange={(e) => setSecondary(e.target.value)} className={`${selectCls} !w-48`} aria-label="Secondary breakdown">
                <option value="">Secondary breakdown…</option>
                {breakdowns.filter((b) => b.value !== breakdown).map((b) => <option key={b.value} value={b.value}>{b.label}</option>)}
              </select>
              <button onClick={() => { setShowSecondary(false); setSecondary(""); }} className="text-slate-400 hover:text-[#0F2440]" aria-label="Remove secondary breakdown"><X size={14} /></button>
            </div>
          )}
          </div>
          <span className="flex-1" />
          {!showFilterRow ? (
            <button onClick={() => setShowFilterRow(true)} className="text-[12px] font-medium text-blue-700 hover:underline" aria-label="Add filter">
              + Add filter
            </button>
          ) : (
          <div className="flex items-center gap-2 min-w-0">
            <select value={filterCol} onChange={(e) => setFilterCol(e.target.value)} className={`${selectCls} !w-40`} aria-label="Filter column">
              {filterCols.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
            <input value={filterVal} onChange={(e) => setFilterVal(e.target.value)} placeholder="value…" className={`${inputCls} !w-32`} aria-label="Filter value" />
            <button
              onClick={() => { if (filterCol && filterVal.trim()) { setFilters((f) => [...f, { column: filterCol, value: filterVal.trim() }]); setFilterVal(""); setShowFilterRow(false); } }}
              disabled={!filterCol || !filterVal.trim()}
              className="text-[12px] font-medium text-blue-700 hover:underline disabled:opacity-40"
            >
              + Add filter
            </button>
            <button onClick={() => setShowFilterRow(false)} className="text-slate-400 hover:text-[#0F2440]" aria-label="Collapse filter"><X size={14} /></button>
          </div>
          )}
          <div className="relative">
            <CalendarDays size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none" />
            <select value={dateRange} onChange={(e) => setDateRange(e.target.value)} className={`${selectCls} !w-48 !pl-8`} aria-label="Date range">
            {dateRanges.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
          </select>
          </div>
        </div>

        {filters.length > 0 && (
          <div className="mt-2 flex items-center gap-1.5 flex-wrap" aria-label="Active filters">
            {filters.map((f, i) => (
              <span key={i} className="inline-flex items-center gap-1 text-[11px] bg-blue-50 text-blue-800 border border-blue-100 rounded-full px-2.5 py-1">
                {humanize(f.column)} = {f.value}
                <button onClick={() => setFilters((list) => list.filter((_, j) => j !== i))} aria-label={`Remove filter ${f.column}`} className="hover:text-blue-900"><X size={11} /></button>
              </span>
            ))}
          </div>
        )}

        
      </Card>

      {/* Running */}
      {running && <LoadingPanel label="Running analysis — calculating from your data…" />}

      {/* Error */}
      {!running && error && <ErrorPanel message={error} requestId={errorId} onRetry={() => runAnalysis()} retryLabel="Run again" />}

      {/* Results: workspace header ditto panel 2 */}
      {!running && !error && result && (
        <div className="text-[11px] text-slate-400 flex items-center gap-1">
          <span>Intelligence</span><ChevronRight size={11} /><span className="text-slate-600 font-medium">Explore</span>
        </div>
      )}
      {!running && !error && result && (
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <h3 className="text-[16px] font-semibold text-[#0F2440] tracking-tight">{trendTitle}</h3>
            <p className="text-[12px] text-slate-500">Explore and analyze your business data.</p>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={saveAnalysis} disabled={saving} className={btnGhost} aria-label="Save result">Save</button>
            <button onClick={() => onAsk(`Share this analysis: ${humanize(metric)} by ${humanize(breakdown)}`)} className={btnGhost} aria-label="Share result">Share</button>
            <button onClick={saveAnalysis} className={btnGhost} aria-label="Export result">Export</button>
          </div>
        </div>
      )}
      {/* Results */}
      {!running && !error && result && (
        <div className="space-y-4 chart-reveal">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <Card className="lg:col-span-2 p-4 md:p-5">
              <CardHead
                title={trendTitle}
                sub={trendSub}
                right={
                  <div className="flex items-center gap-1.5 text-[11px] font-medium border border-slate-200 rounded-lg px-2 py-1" aria-label="Chart type">
                    <BarChart3 size={12} className="text-blue-700" />
                    <select value={chartMode} onChange={(e) => setChartMode(e.target.value as "bar" | "line")} className="bg-transparent outline-none cursor-pointer text-[#0F2440]" aria-label="Chart type">
                      <option value="bar">Bar Chart</option>
                      <option value="line">Line Chart</option>
                    </select>
                  </div>
                }
              />
              {trendPoints.length > 0 ? (
                <div className="h-[260px] mt-2">
                  <ResponsiveContainer width="100%" height="100%">
                    {chartMode === "bar" ? (
                      <BarChart data={trendPoints} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
                        <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} minTickGap={24} />
                        <YAxis tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} width={52} tickFormatter={(v: number) => fmtBiz(v)} />
                        <Tooltip formatter={(v: any, name: any) => [fmtMetric(numOf(v), trendTitle), humanize(String(name))]} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="current" name="Current Period" fill="#2F6FAD" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="previous" name="Previous Period" fill="#B9D0E8" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    ) : (
                      <LineChart data={trendPoints} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
                        <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} minTickGap={24} />
                        <YAxis tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} width={52} tickFormatter={(v: number) => fmtBiz(v)} />
                        <Tooltip formatter={(v: any, name: any) => [fmtMetric(numOf(v), trendTitle), humanize(String(name))]} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Line type="monotone" dataKey="current" name="Current Period" stroke="#2F6FAD" strokeWidth={2.5} dot={false} />
                        <Line type="monotone" dataKey="previous" name="Previous Period" stroke="#B9D0E8" strokeWidth={2} strokeDasharray="5 4" dot={false} />
                      </LineChart>
                    )}
                  </ResponsiveContainer>
                </div>
              ) : (
                <p className="text-xs text-slate-500 mt-3">The backend returned no trend points for this selection — try a different metric or range.</p>
              )}
            </Card>

            <Card className="p-4 md:p-5">
              <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
                <Sparkles size={14} className="text-blue-700" /> ARIA Observation
              </h3>
              {obsSummary ? (
                <div className="mt-2">
                  <p className="text-[12.5px] text-slate-700 leading-relaxed">{obsSummary}</p>
                  {obsBullets.length > 0 && (
                    <ul className="mt-2 space-y-1.5">
                      {obsBullets.map((b, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-[12px] text-slate-600 leading-relaxed">
                          <span className="w-1.5 h-1.5 rounded-full bg-blue-600 flex-shrink-0 mt-1.5" />{b}
                        </li>
                      ))}
                    </ul>
                  )}
                  {(obsBasis || `This analysis is based on your connected data${trendSub ? ` (${trendSub})` : ""}.`) && (
                    <p className="mt-3 text-[11px] text-slate-500 bg-slate-50 border border-slate-100 rounded-xl px-2.5 py-2">{obsBasis || `This analysis is based on your connected data${trendSub ? ` (${trendSub})` : ""}.`}</p>
                  )}
                  <button onClick={() => { try { document.getElementById("intel-breakdown-table")?.scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} }} className="mt-2 inline-flex items-center gap-1 text-[11.5px] font-semibold text-blue-700 hover:underline" aria-label="View evidence">View Evidence <ChevronRight size={12} /></button>
                </div>
              ) : (
                <p className="text-xs text-slate-500 mt-2">No observation was returned for this analysis.</p>
              )}
            </Card>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <div id="intel-breakdown-table" className="lg:col-span-2"><Card className="p-4 md:p-5 overflow-hidden">
              <CardHead title={breakdownTitle} sub="Revenue, comparison and change by product category" />
              {rows.length > 0 ? (
                <div className="mt-2 overflow-x-auto -mx-4 px-4 md:-mx-5 md:px-5">
                  <table className="w-full text-[12px] min-w-[560px]">
                    <thead>
                      <tr className="text-left text-slate-500 border-b border-slate-100">
                        <th scope="col" className="py-2 pr-3 font-medium">{humanize(breakdown) || "Category"}</th>
                        <th scope="col" className="py-2 pr-3 font-medium text-right">Current Period</th>
                        <th scope="col" className="py-2 pr-3 font-medium text-right">Previous Period</th>
                        <th scope="col" className="py-2 pr-3 font-medium text-right">Change</th>
                        <th scope="col" className="py-2 pr-3 font-medium text-right">% Change</th>
                        <th scope="col" className="py-2 font-medium text-right">Trend</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r: any, i: number) => {
                        const cur = numOf(r?.current ?? r?.current_value ?? r?.value);
                        const prev = numOf(r?.previous ?? r?.previous_value ?? r?.prev);
                        const chg = numOf(r?.change ?? r?.delta);
                        const pct = numOf(r?.change_pct ?? r?.pct_change ?? r?.pct ?? r?.percent_change);
                        const spark = asList(r?.trend || r?.spark || r?.history).map((v) => numOf(typeof v === "number" ? v : v?.value ?? v?.v)).filter((v) => v !== null) as number[];
                        const up = (chg ?? 0) >= 0;
                        return (
                          <tr key={i} className="border-b border-slate-50 last:border-0">
                            <td className="py-2 pr-3 font-medium text-[#0F2440]">
                              <span className="inline-flex items-center gap-2">
                                <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: colorForName(strOf(r?.category || r?.label || r?.name)) }} />
                                {strOf(r?.category || r?.label || r?.name || `Row ${i + 1}`)}
                              </span>
                            </td>
                            <td className="py-2 pr-3 text-right tabular-nums">{cur === null ? "—" : fmtMetric(cur, metric)}</td>
                            <td className="py-2 pr-3 text-right tabular-nums text-slate-500">{prev === null ? "—" : fmtMetric(prev, metric)}</td>
                            <td className={`py-2 pr-3 text-right tabular-nums font-medium ${chg === null ? "text-slate-400" : up ? "text-emerald-600" : "text-rose-600"}`}>
                              {chg === null ? "—" : <span className="inline-flex items-center gap-0.5 justify-end">{up ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}{fmtMetric(Math.abs(chg), metric)}</span>}
                            </td>
                            <td className={`py-2 pr-3 text-right tabular-nums font-medium ${pct === null ? "text-slate-400" : pct >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                              {pct === null ? "—" : fmtPctBiz(pct)}
                            </td>
                            <td className="py-1 text-right">
                              {spark.length > 1 ? (
                                <div className="w-20 h-7 inline-block" aria-hidden>
                                  <ResponsiveContainer width="100%" height="100%">
                                    <LineChart data={spark.map((v) => ({ v }))}>
                                      <Line type="monotone" dataKey="v" stroke="#2F6FAD" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                                    </LineChart>
                                  </ResponsiveContainer>
                                </div>
                              ) : <span className="text-slate-300">—</span>}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-xs text-slate-500 mt-3">No breakdown rows were returned for this selection.</p>
              )}
            </Card></div>

            <Card className="p-4 md:p-5">
              <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
                <Send size={13} className="text-blue-700" /> Next Steps
              </h3>
              <p className="text-[11px] text-slate-500">Take the next step with this analysis.</p>
              <div className="mt-2 divide-y divide-slate-100">
                {nextSteps.map(({ label, sub, tab, Icon }) => (
                  <button key={label} onClick={() => onGoto(tab)} className="w-full text-left py-2.5 flex items-center gap-2.5 hover:bg-blue-50/50 rounded-lg px-1 -mx-1 transition-colors group">
                    <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-blue-50 text-blue-700 flex-shrink-0"><Icon size={13} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] font-medium text-[#0F2440] group-hover:text-blue-700">{label}</span>
                      <span className="block text-[11px] text-slate-400">{sub}</span>
                    </span>
                    <ChevronRight size={13} className="text-slate-300 group-hover:text-blue-500 flex-shrink-0" />
                  </button>
                ))}
                <button onClick={() => onAsk(`Explain this analysis: ${humanize(metric)} by ${humanize(breakdown)}`)} className="w-full text-left py-2.5 flex items-center gap-2.5 hover:bg-blue-50/50 rounded-lg px-1 -mx-1 transition-colors group">
                  <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-violet-50 text-violet-700 flex-shrink-0"><Sparkles size={13} /></span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[12.5px] font-medium text-[#0F2440] group-hover:text-blue-700">Ask ARIA</span>
                    <span className="block text-[11px] text-slate-400">Get a deeper explanation</span>
                  </span>
                  <ChevronRight size={13} className="text-slate-300 group-hover:text-blue-500 flex-shrink-0" />
                </button>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* Home state: quick actions + recent + saved */}
      {!running && !error && !result && (
        <div className="space-y-4">
          <Card className="p-4 md:p-5">
            <Card className="p-4 md:p-5">
            <CardHead title="Start an analysis" sub="Ask anything — ARIA will run it against your connected data." />
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50/60 px-3 py-2 focus-within:border-blue-400 transition-colors">
              <span className="text-slate-400 text-[13px]">Q</span>
              <input value={homeQuery} onChange={(e) => setHomeQuery(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") submitHomeQuery(); }} placeholder="What would you like to investigate?" className="flex-1 bg-transparent outline-none text-[13px] text-[#0F2440] placeholder:text-slate-400" aria-label="What would you like to investigate" />
              <button onClick={submitHomeQuery} className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-blue-700 text-white hover:bg-blue-800 transition-colors" aria-label="Start analysis"><Play size={14} /></button>
            </div>
            <div className="mt-2.5 flex items-center gap-1.5 flex-wrap" aria-label="Suggested investigations">
              {HOME_SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => { setHomeQuery(s); onAsk(s); setTimeout(() => runAnalysis(), 120); }} className="text-[11px] text-slate-500 border border-slate-200 rounded-full px-2.5 py-1 hover:border-blue-300 hover:text-blue-700 bg-white transition-colors">{s}</button>
              ))}
            </div>
          </Card>
          <CardHead title="Quick Analysis Actions" sub="Start from a common investigation — ARIA fills the builder and runs it." />
            <div className="mt-3 grid grid-cols-2 md:grid-cols-4 gap-2">
              {QUICK_ACTIONS.map(({ id, label, sub, Icon }) => (
                <button key={id} onClick={() => quickRun(id)} className="text-left rounded-xl border border-slate-200 hover:border-blue-300 hover:shadow-sm p-3 transition-all group" aria-label={label}>
                  <span className="inline-flex items-center justify-center w-7 h-7 rounded-lg bg-blue-50 text-blue-700 mb-1.5"><Icon size={14} /></span>
                  <span className="block text-[12.5px] font-medium text-[#0F2440] group-hover:text-blue-700">{label}</span>
                  <span className="block text-[11px] text-slate-400">{sub}</span>
                </button>
              ))}
            </div>
          </Card>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card className="p-4 md:p-5">
              <CardHead title="Recent Analyses" sub="Your latest explorations." right={<button onClick={() => setShowAllRecent((v) => !v)} className="text-[11px] font-semibold text-blue-700 hover:underline">{showAllRecent ? "Show less" : "View all"}</button>} />
              <div className="mt-2 divide-y divide-slate-100">
                {recent.length === 0 && <p className="text-[12px] text-slate-400 py-3">No recent analyses yet — run your first analysis above.</p>}
                {(showAllRecent ? recent : recent.slice(0, 4)).map((a: any, i: number) => (
                  <div key={strOf(a?.id || i)} className="py-2 flex items-center gap-2">
                    <BarChart3 size={13} className="text-blue-600 flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[12.5px] font-medium text-[#0F2440] truncate">{strOf(a?.title || a?.name || `${humanize(a?.metric)} by ${humanize(a?.breakdown)}`, "Analysis")}</p>
                      <p className="text-[11px] text-slate-400">{relativeOpened(strOf(a?.updated_at || a?.created_at || ""))}</p>
                    </div>
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100">{strOf(a?.type || "Explore")}</span>
                    <button onClick={() => loadSavedAnalysis(a)} className="text-[11px] font-semibold text-blue-700 hover:underline" aria-label={`Reload analysis ${strOf(a?.title || "")}`}>View</button>
                    {strOf(a?.id) && <button onClick={() => deleteSavedAnalysis(strOf(a.id))} className="text-[11px] font-medium text-slate-400 hover:text-rose-600" aria-label={`Delete analysis ${strOf(a?.title || "")}`}>Delete</button>}
                  </div>
                ))}
              </div>
            </Card>
            <Card className="p-4 md:p-5">
              <CardHead title="Saved Collections" sub="Analyses you kept for later." right={<button onClick={() => setShowAllSaved((v) => !v)} className="text-[11px] font-semibold text-blue-700 hover:underline">{showAllSaved ? "Show less" : "View all"}</button>} />
              <div className="mt-2 divide-y divide-slate-100">
                {savedCols.length === 0 && <p className="text-[12px] text-slate-400 py-3">Nothing saved yet — use Save Analysis on any result.</p>}
                {(showAllSaved ? savedCols : savedCols.slice(0, 4)).map((a: any, i: number) => (
                  <div key={strOf(a?.id || i)} className="py-2 flex items-center gap-2">
                    <Bookmark size={13} className="text-violet-600 flex-shrink-0" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[12.5px] font-medium text-[#0F2440] truncate">{strOf(a?.title || a?.name || a?.collection || "Saved analysis")}</p>
                      <p className="text-[11px] text-slate-400">{relativeOpened(strOf(a?.updated_at || a?.created_at || ""))}</p>
                    </div>
                    <button onClick={() => loadSavedAnalysis(a)} className="text-[11px] font-semibold text-blue-700 hover:underline" aria-label={`Reload saved analysis ${strOf(a?.title || "")}`}>View</button>
                    {strOf(a?.id) && <button onClick={() => deleteSavedAnalysis(strOf(a.id))} className="text-[11px] font-medium text-slate-400 hover:text-rose-600" aria-label={`Delete saved analysis ${strOf(a?.title || "")}`}>Delete</button>}
                  </div>
                ))}
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2">
                {(showAllSaved ? savedBuckets : savedBuckets.slice(0, 4)).map((b) => (
                  <button key={b.name} onClick={() => { const first = b.items[0]; if (first) loadSavedAnalysis(first); }} className="text-left rounded-xl border border-slate-200 p-3 hover:border-blue-300 hover:shadow-sm transition-all flex items-center gap-2" aria-label={`Open ${b.name} collection`}>
                    <Bookmark size={13} className="text-violet-600 flex-shrink-0" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-[12.5px] font-semibold text-[#0F2440] truncate">{b.name}</span>
                      <span className="block text-[11px] text-slate-400">{b.count} analyses</span>
                    </span>
                    <ChevronRight size={13} className="text-slate-300" />
                  </button>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}
    </div>
  );
}

/* =====================================================================
   HYPOTHESES
   ===================================================================== */

function HypothesesTab({ onAsk }: { onAsk: (q: string) => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [errorId, setErrorId] = useState("");
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [sort, setSort] = useState("recent");
  const [page, setPage] = useState(1);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [detailTab, setDetailTab] = useState("results");
  const PAGE_SIZE = 8;

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(search.trim()); setPage(1); }, 350);
    return () => clearTimeout(t);
  }, [search]);

  const fetchList = useCallback(async () => {
    setLoading(true);
    setError("");
    setErrorId("");
    try {
      const r = await intelligenceApi.listHypotheses({ search: debounced || undefined, sort, page, page_size: PAGE_SIZE });
      setItems(asList(r.data));
      setTotal(typeof r.total === "number" ? r.total : null);
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setError(norm.message);
      setErrorId(norm.requestId);
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [debounced, sort, page]);
  useEffect(() => { fetchList(); }, [fetchList]);

  const openDetail = async (id: string) => {
    setSelectedId(id);
    setDetailTab("results");
    setDetailLoading(true);
    setDetailError("");
    setDetail(null);
    try {
      const r = await intelligenceApi.getHypothesis(id);
      setDetail(r.data || null);
    } catch (e: any) {
      const local = items.find((h) => strOf(h?.id) === id);
      if (local) setDetail(local);
      else setDetailError(businessError(e?.message) || "ARIA couldn't load this hypothesis.");
    } finally {
      setDetailLoading(false);
    }
  };

  const pages = total !== null ? Math.max(1, Math.ceil(total / PAGE_SIZE)) : null;

  if (selectedId) {
    const h = detail || {};
    const ctx = h?.context || h?.analysis_context || {};
    const pattern = h?.observed_pattern || h?.pattern || null;
    const takeaways: string[] = asList(h?.key_takeaways || h?.takeaways).map((t) => strOf(typeof t === "string" ? t : t?.text)).filter(Boolean).slice(0, 6);
    const factors = asList(h?.associated_factors || h?.factors).filter(isValidFactor);
    const evidence: string[] = asList(h?.evidence || h?.evidence_points || h?.observations).map((e) => strOf(typeof e === "string" ? e : e?.text || e?.observation)).filter(Boolean).slice(0, 8);
    const related = asList(h?.related || h?.related_analyses);
    const nextSteps: string[] = asList(h?.next_steps || h?.nextSteps).map((s) => strOf(typeof s === "string" ? s : s?.text || s?.label)).filter(Boolean).slice(0, 5);
    const detailTabs = [
      { id: "results", label: "Hypothesis Results" },
      { id: "factors", label: "Associated Factors" },
      { id: "evidence", label: "Evidence" },
      { id: "related", label: "Related Analyses" },
    ];
    return (
      <div className="space-y-4">
        <div className="text-[11px] text-slate-400 flex items-center gap-1"><span>Intelligence</span><ChevronRight size={11} /><span className="text-slate-600 font-medium">Hypotheses</span></div>
        <button onClick={() => { setSelectedId(null); setDetail(null); }} className="inline-flex items-center gap-1.5 text-[12.5px] font-semibold text-blue-700 hover:underline" aria-label="Back to hypotheses">
          <ArrowLeft size={13} /> Hypotheses
        </button>
        {detailLoading && <LoadingPanel label="Loading hypothesis detail…" />}
        {!detailLoading && detailError && <ErrorPanel message={detailError} onRetry={() => selectedId && openDetail(selectedId)} />}
        {!detailLoading && !detailError && (
          <>
            <h3 className="text-[16px] font-semibold text-[#0F2440] tracking-tight">{strOf(h?.title || h?.question || "Hypothesis", "Hypothesis")}</h3>
            <p className="text-[12px] text-slate-500 -mt-3">Investigate potential factors behind the observed pattern.</p>
            <Card className="p-4 md:p-5">
              <div className="flex items-center justify-between gap-2 flex-wrap">
                <h4 className="text-[13px] font-semibold text-[#0F2440]">Analysis Context</h4>
                <button onClick={() => { try { window.location.hash = "#/intelligence?tab=explore"; } catch {} }} className="text-[11px] font-semibold text-blue-700 hover:underline" aria-label="Edit context">Edit Context</button>
              </div>
              <dl className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-3 text-[12px]">
                {[["Metric", ctx?.metric || h?.metric], ["Time Period", ctx?.period || ctx?.time_period || h?.period], ["Breakdown", ctx?.breakdown || ctx?.dimension || h?.dimension], ["Filters", ctx?.filters ? (Array.isArray(ctx.filters) ? ctx.filters.map((f: any) => typeof f === "string" ? f : `${f?.column || ""} = ${f?.value || ""}`).join("; ") : strOf(ctx.filters)) : "—"]].map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-[11px] text-slate-400">{k}</dt>
                    <dd className="font-medium text-[#0F2440] mt-0.5">{strOf(v || "—")}</dd>
                  </div>
                ))}
              </dl>
            </Card>
            <div className="flex items-center gap-1 border-b border-slate-200" role="tablist" aria-label="Hypothesis detail">
              {detailTabs.map((t) => (
                <button key={t.id} role="tab" aria-selected={detailTab === t.id} onClick={() => setDetailTab(t.id)}
                  className={`px-3 py-2 text-[12.5px] font-medium border-b-2 -mb-px transition-colors ${detailTab === t.id ? "border-blue-700 text-[#0F2440]" : "border-transparent text-slate-400 hover:text-slate-600"}`}>
                  {t.label}
                </button>
              ))}
            </div>
            {(detailTab === "results") && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <Card className="p-4 md:p-5">
                  <h4 className="text-[13px] font-semibold text-[#0F2440]">Observed Pattern</h4>
                  {pattern ? (
                    <div className="mt-2">
                      <p className="text-[13px] font-medium text-[#0F2440]">{strOf(pattern?.headline || pattern?.title || pattern?.summary || "")}</p>
                      {asList(pattern?.series || pattern?.points).length > 1 && (
                        <div className="h-28 mt-2" aria-hidden>
                          <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={asList(pattern.series || pattern.points).map((v: any, i: number) => ({ i, v: numOf(typeof v === "number" ? v : v?.value ?? v?.v) ?? 0 }))}>
                              <Line type="monotone" dataKey="v" stroke="#4F46E5" strokeWidth={2} dot={false} isAnimationActive={false} />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      )}
                      {strOf(pattern?.detail || pattern?.description) && <p className="text-[12px] text-slate-600 mt-2 leading-relaxed">{strOf(pattern.detail || pattern.description)}</p>}
                    </div>
                  ) : <p className="text-[12px] text-slate-400 mt-2">No observed pattern was returned for this hypothesis.</p>}
                </Card>
                <Card className="p-4 md:p-5">
                  <h4 className="text-[13px] font-semibold text-[#0F2440]">Key Takeaways</h4>
                  {takeaways.length ? (
                    <ul className="mt-2 space-y-1.5">
                      {takeaways.map((t, i) => (
                        <li key={i} className="flex items-start gap-1.5 text-[12px] text-slate-600 leading-relaxed">
                          <Check size={13} className="text-emerald-600 flex-shrink-0 mt-0.5" />{t}
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-[12px] text-slate-400 mt-2">No takeaways were returned for this hypothesis.</p>}
                </Card>
              </div>
            )}
            {detailTab === "factors" && (
              <Card className="p-4 md:p-5 overflow-hidden">
                <h4 className="text-[13px] font-semibold text-[#0F2440]">Potential Associated Factors</h4>
                {factors.length ? (
                  <div className="mt-2 overflow-x-auto">
                    <table className="w-full text-[12px] min-w-[560px]">
                      <thead>
                        <tr className="text-left text-slate-500 border-b border-slate-100">
                          <th scope="col" className="py-2 pr-3 font-medium">Factor</th>
                          <th scope="col" className="py-2 pr-3 font-medium">Type</th>
                          <th scope="col" className="py-2 pr-3 font-medium">Association</th>
                          <th scope="col" className="py-2 pr-3 font-medium">Evidence Strength</th>
                          <th scope="col" className="py-2 font-medium text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {factors.map((f: any, i: number) => (
                          <tr key={i} className="border-b border-slate-50 last:border-0">
                            <td className="py-2 pr-3 font-medium text-[#0F2440]">{strOf(f?.factor || f?.name || `Factor ${i + 1}`)}</td>
                            <td className="py-2 pr-3 text-slate-500">{humanize(strOf(f?.type || f?.kind || "—"))}</td>
                            <td className="py-2 pr-3 text-slate-600">{strOf(f?.association || f?.relationship || "—")}</td>
                            <td className="py-2 pr-3"><span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${/strong/i.test(strOf(f?.evidence_strength || f?.strength || "")) ? "bg-rose-50 text-rose-700 border-rose-200" : /moderate/i.test(strOf(f?.evidence_strength || f?.strength || "")) ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-blue-50 text-blue-700 border-blue-100"}`}>{humanize(strOf(f?.evidence_strength || f?.strength || "—"))}</span></td>
                            <td className="py-2 text-right">
                              <button onClick={() => onAsk(`Explain the link between ${strOf(f?.factor || f?.name)} and ${strOf(h?.title || "this pattern")}`)} className="inline-flex items-center gap-1 text-[11.5px] font-medium text-blue-700 hover:underline" aria-label={`View factor ${strOf(f?.factor || f?.name)}`}>
                                <Eye size={12} /> View
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    <p className="mt-2 text-[11px] text-slate-400">These factors are associated with the observed pattern. They do not necessarily establish causation.</p>
                  </div>
                ) : (
                  <p className="text-[12px] text-slate-400 mt-2">No independently supported associated factors were found — weak or structural-only links are never promoted into factors.</p>
                )}
              </Card>
            )}
            {detailTab === "evidence" && (
              <Card className="p-4 md:p-5">
                <h4 className="text-[13px] font-semibold text-[#0F2440]">Evidence</h4>
                {evidence.length ? (
                  <ul className="mt-2 space-y-1.5">
                    {evidence.map((e, i) => <li key={i} className="text-[12px] text-slate-600 leading-relaxed">· {e}</li>)}
                  </ul>
                ) : <p className="text-[12px] text-slate-400 mt-2">No evidence points were returned for this hypothesis.</p>}
              </Card>
            )}
            {detailTab === "related" && (
              <Card className="p-4 md:p-5">
                <h4 className="text-[13px] font-semibold text-[#0F2440]">Related</h4>
                {related.length ? (
                  <div className="mt-2 divide-y divide-slate-100">
                    {related.map((r: any, i: number) => (
                      <button key={i} onClick={() => { const id = strOf(r?.id); if (id) openDetail(id); }} className="w-full text-left py-2 hover:text-blue-700 text-[12.5px] font-medium text-[#0F2440]">
                        {strOf(r?.title || r?.question || `Related ${i + 1}`)}
                      </button>
                    ))}
                  </div>
                ) : <p className="text-[12px] text-slate-400 mt-2">No related analyses were returned.</p>}
              </Card>
            )}
            {nextSteps.length > 0 && (
              <Card className="p-4 md:p-5">
                <h4 className="text-[13px] font-semibold text-[#0F2440]">Next Steps</h4>
                <ul className="mt-2 space-y-1.5">
                  {nextSteps.map((s, i) => <li key={i} className="text-[12px] text-slate-600 leading-relaxed">· {s}</li>)}
                </ul>
              </Card>
            )}
          </>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 md:p-5">
        <div className="flex items-center gap-2 flex-wrap">
          <div className="flex-1 min-w-44">
            <label htmlFor="hyp-search" className="sr-only">Search hypotheses</label>
            <input id="hyp-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search hypotheses…" className={inputCls} aria-label="Search hypotheses" />
          </div>
          <label className="text-[11px] text-slate-500 flex items-center gap-1.5">
            Sort
            <select value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }} className={`${selectCls} !w-auto`} aria-label="Sort hypotheses">
              <option value="recent">Most recent</option>
              <option value="strongest">Strongest evidence</option>
              <option value="az">Title A–Z</option>
            </select>
          </label>
          <button onClick={fetchList} className={btnGhost} aria-label="Refresh hypotheses"><RefreshCw size={13} /> Refresh</button>
        </div>
      </Card>

      {loading && <LoadingPanel label="Loading hypotheses…" />}
      {!loading && error && <ErrorPanel message={error} requestId={errorId} onRetry={fetchList} />}
      {!loading && !error && items.length === 0 && (
        <EmptyPanel
          icon={Lightbulb}
          title="No hypotheses found yet."
          body="ARIA promotes a hypothesis only when the observed pattern has enough supporting evidence. Try a broader search, or run an analysis in Explore first."
          action={<button onClick={() => { setSearch(""); setPage(1); fetchList(); }} className="text-xs font-semibold text-blue-700 hover:underline">Clear search</button>}
        />
      )}
      {!loading && !error && items.length > 0 && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {items.map((h: any) => (
              <Card key={strOf(h?.id || h?.title)} className="p-4 hover:border-blue-200 hover:shadow-md transition-all">
                <p className="text-[13px] font-semibold text-[#0F2440] leading-snug">{strOf(h?.title || h?.question || "Hypothesis")}</p>
                <p className="text-[12px] text-slate-500 mt-1 line-clamp-2 leading-relaxed">{strOf(h?.summary || h?.observed_pattern?.headline || h?.description || "")}</p>
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  {strOf(h?.evidence_strength || h?.strength) && (
                    <span className="text-[10.5px] font-semibold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-100">{humanize(strOf(h.evidence_strength || h.strength))} evidence</span>
                  )}
                  {strOf(h?.status) && <span className="text-[10.5px] text-slate-500">{humanize(strOf(h.status))}</span>}
                  <button onClick={() => openDetail(strOf(h?.id))} disabled={!h?.id} className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-blue-700 hover:underline disabled:opacity-40" aria-label={`View hypothesis ${strOf(h?.title || "")}`}>
                    <Eye size={12} /> View
                  </button>
                </div>
              </Card>
            ))}
          </div>
          {pages !== null && pages > 1 && (
            <div className="flex items-center justify-center gap-2" role="navigation" aria-label="Hypotheses pages">
              <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1} className={btnGhost} aria-label="Previous page">← Prev</button>
              <span className="text-[12px] text-slate-500">Page {page} of {pages}{total !== null ? ` · ${total} total` : ""}</span>
              <button onClick={() => setPage((p) => Math.min(pages, p + 1))} disabled={page >= pages} className={btnGhost} aria-label="Next page">Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/* =====================================================================
   GOALS
   ===================================================================== */

type GoalFilter = "active" | "completed" | "paused" | "all";

function GoalsTab({ meta }: { meta: any }) {
  const [filter, setFilter] = useState<GoalFilter>("active");
  const [goals, setGoals] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [errorId, setErrorId] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [fTitle, setFTitle] = useState("");
  const [fMetric, setFMetric] = useState("");
  const [fTarget, setFTarget] = useState("");
  const [fDue, setFDue] = useState("");
  const [formError, setFormError] = useState("");
  const [formBusy, setFormBusy] = useState(false);
  const [actingId, setActingId] = useState<string | null>(null);

  const metrics: string[] = useMemo(() => {
    const m = meta?.metrics ?? meta?.measures ?? [];
    return asList(m).map((x) => strOf(typeof x === "string" ? x : x?.name || x?.label)).filter(Boolean);
  }, [meta]);

  const fetchGoals = useCallback(async () => {
    setLoading(true);
    setError("");
    setErrorId("");
    try {
      const r = await intelligenceApi.listGoals({ status: filter === "all" ? undefined : filter, sort: "due" });
      setGoals(asList(r.data));
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setError(norm.message);
      setErrorId(norm.requestId);
      setGoals([]);
    } finally {
      setLoading(false);
    }
  }, [filter]);
  useEffect(() => { fetchGoals(); }, [fetchGoals]);

  const createGoal = async () => {
    setFormError("");
    if (!fTitle.trim() || !fTarget.trim()) { setFormError("Give the goal a title and a target value."); return; }
    setFormBusy(true);
    try {
      await intelligenceApi.createGoal({ title: fTitle.trim(), metric: fMetric || undefined, target: fTarget.trim(), due_date: fDue || undefined, status: "active" });
      setShowForm(false);
      setFTitle(""); setFMetric(""); setFTarget(""); setFDue("");
      setFilter("active");
      fetchGoals();
    } catch (e: any) {
      setFormError(businessError(e?.message) || "ARIA couldn't save this goal.");
    } finally {
      setFormBusy(false);
    }
  };

  const deleteGoal = async (id: string) => {
    if (!id) return;
    setActingId(id);
    try {
      await intelligenceApi.deleteGoal(id);
      fetchGoals();
    } catch (e: any) {
      setError(businessError(e?.message) || "ARIA couldn't delete this goal.");
    } finally {
      setActingId(null);
    }
  };

  const setStatus = async (id: string, status: string) => {
    setActingId(id);
    try {
      await intelligenceApi.updateGoal(id, { status });
      fetchGoals();
    } catch (e: any) {
      setError(businessError(e?.message) || "ARIA couldn't update this goal.");
    } finally {
      setActingId(null);
    }
  };

  const statusTone = (s: string) => {
    const t = s.toLowerCase();
    if (/behind|at risk|off track/.test(t)) return "bg-rose-50 text-rose-700 border-rose-200";
    if (/near|close|watch/.test(t)) return "bg-amber-50 text-amber-700 border-amber-200";
    if (/on track|ahead|complete|achieved/.test(t)) return "bg-emerald-50 text-emerald-700 border-emerald-200";
    return "bg-slate-50 text-slate-600 border-slate-200";
  };

  const filters: { id: GoalFilter; label: string }[] = [
    { id: "active", label: "Active Goals" },
    { id: "completed", label: "Completed" },
    { id: "paused", label: "Paused" },
    { id: "all", label: "All Goals" },
  ];

  if (!loading && !error && metrics.length === 0 && goals.length === 0) {
    return (
      <div className="space-y-4">
        <NoDatasetPanel onRetry={fetchGoals} />
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <div className="text-[11px] text-slate-400 flex items-center gap-1">
        <span>Intelligence</span><ChevronRight size={11} /><span className="text-slate-600 font-medium">Goals</span>
      </div>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-[16px] font-semibold text-[#0F2440] tracking-tight">Business Goals</h3>
          <p className="text-[12px] text-slate-500">Track your targets and monitor progress.</p>
        </div>
        <button onClick={() => setShowForm((v) => !v)} className={btnPrimary} aria-label="Create goal">
          <Plus size={13} /> Create Goal
        </button>
      </div>

      {showForm && (
        <Card className="p-4 md:p-5">
          <h4 className="text-[13px] font-semibold text-[#0F2440]">Set a new goal</h4>
          <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3">
            <Field label="Goal title" htmlFor="goal-title">
              <input id="goal-title" value={fTitle} onChange={(e) => setFTitle(e.target.value)} placeholder="e.g. Grow monthly revenue" className={inputCls} aria-label="Goal title" />
            </Field>
            <Field label="Metric" htmlFor="goal-metric">
              <select id="goal-metric" value={fMetric} onChange={(e) => setFMetric(e.target.value)} className={selectCls} aria-label="Goal metric">
                <option value="">Select a metric…</option>
                {metrics.map((m) => <option key={m} value={m}>{humanize(m)}</option>)}
              </select>
            </Field>
            <Field label="Target value" htmlFor="goal-target">
              <input id="goal-target" value={fTarget} onChange={(e) => setFTarget(e.target.value)} placeholder="e.g. 350000" inputMode="decimal" className={inputCls} aria-label="Target value" />
            </Field>
            <Field label="Due date" htmlFor="goal-due">
              <input id="goal-due" type="date" value={fDue} onChange={(e) => setFDue(e.target.value)} className={inputCls} aria-label="Due date" />
            </Field>
          </div>
          {formError && <p className="mt-2 text-[12px] text-rose-600" role="alert">{formError}</p>}
          <div className="mt-3 flex items-center gap-2">
            <button onClick={createGoal} disabled={formBusy} className={btnPrimary} aria-label="Save goal">
              {formBusy ? "Saving…" : "Save Goal"}
            </button>
            <button onClick={() => { setShowForm(false); setFormError(""); }} className={btnGhost}>Cancel</button>
          </div>
        </Card>
      )}

      <div className="flex items-center gap-1 border-b border-slate-200" role="tablist" aria-label="Goal status filter">
        {filters.map((f) => (
          <button key={f.id} role="tab" aria-selected={filter === f.id} onClick={() => setFilter(f.id)}
            className={`px-3 py-2 text-[12.5px] font-medium border-b-2 -mb-px transition-colors ${filter === f.id ? "border-blue-700 text-[#0F2440]" : "border-transparent text-slate-400 hover:text-slate-600"}`}>
            {f.label}
          </button>
        ))}
        <button onClick={fetchGoals} className="ml-auto p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-[#0F2440]" title="Refresh goals" aria-label="Refresh goals">
          <RefreshCw size={13} />
        </button>
      </div>

      {loading && <LoadingPanel label="Loading goals…" />}
      {!loading && error && <ErrorPanel message={error} requestId={errorId} onRetry={fetchGoals} />}
      {!loading && !error && goals.length === 0 && (
        <EmptyPanel
          icon={Target}
          title={filter === "all" ? "No goals yet." : `No ${filter} goals.`}
          body="Define a target, track progress, and let ARIA help you stay on track. Goals persist, so they survive a reload."
          action={<button onClick={() => setShowForm(true)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 hover:underline"><Plus size={12} /> Set your first goal</button>}
        />
      )}
      {!loading && !error && goals.length > 0 && (
        <div className="space-y-3">
          {goals.map((g: any) => {
            const id = strOf(g?.id || g?.goal_id);
            const cur = numOf(g?.current ?? g?.current_value);
            const tgt = numOf(g?.target ?? g?.target_value);
            const delta = numOf(g?.delta ?? g?.difference);
            const deltaPct = numOf(g?.delta_pct ?? g?.delta_percent ?? g?.pct_off);
            const prog = numOf(g?.progress ?? g?.progress_pct ?? g?.percent_complete);
            const status = strOf(g?.status_label || g?.status || "");
            const due = strOf(g?.due_date || g?.due || "");
            return (
              <Card key={id || strOf(g?.title)} className="p-4">
                <div className="flex items-start gap-3 flex-wrap">
                  <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-violet-50 text-violet-700 flex-shrink-0"><Target size={15} /></span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[13.5px] font-semibold text-[#0F2440]">{strOf(g?.title || g?.name || "Goal")}</p>
                    <p className="text-[11px] text-slate-400 mt-0.5 flex items-center gap-1">
                      <CalendarDays size={11} /> {due ? `Due ${due}` : "No due date"}{strOf(g?.metric) ? ` · ${humanize(strOf(g.metric))}` : ""}
                    </p>
                    <div className="mt-2 flex items-center gap-4 flex-wrap text-[12px]">
                      <span className="text-slate-500">Current <span className="font-semibold text-[#0F2440] tabular-nums">{cur === null ? "—" : fmtBiz(cur)}</span></span>
                      <span className="text-slate-500">Target <span className="font-semibold text-[#0F2440] tabular-nums">{tgt === null ? "—" : fmtBiz(tgt)}</span></span>
                      {(delta !== null || deltaPct !== null) && (
                        <span className={`font-semibold tabular-nums ${(delta ?? 0) >= 0 ? "text-emerald-600" : "text-rose-600"}`}>
                          {delta !== null ? fmtBiz(delta) : ""}{deltaPct !== null ? ` (${fmtPctBiz(deltaPct)})` : ""}
                        </span>
                      )}
                    </div>
                    {prog !== null && (
                      <div className="mt-2 max-w-md">
                        <div className="h-1.5 rounded-full bg-slate-100 overflow-hidden" role="progressbar" aria-valuenow={Math.round(prog)} aria-valuemin={0} aria-valuemax={100} aria-label={`Progress for ${strOf(g?.title)}`}>
                          <div className={`h-full rounded-full ${/behind|at risk|off track/i.test(status) ? "bg-gradient-to-r from-rose-500 to-rose-400" : /near|watch/i.test(status) ? "bg-gradient-to-r from-amber-500 to-amber-400" : "bg-gradient-to-r from-emerald-500 to-emerald-400"}`} style={{ width: `${Math.max(0, Math.min(100, prog))}%` }} />
                        </div>
                      </div>
                    )}
                  </div>
                  <div className="flex flex-col items-end gap-2">
                    {status && <span className={`text-[10.5px] font-semibold px-2 py-0.5 rounded-full border ${statusTone(status)}`}>{status}</span>}
                    {filter !== "completed" && (
                      <div className="flex items-center gap-1.5">
                        {filter !== "paused" && (
                          <button onClick={() => id && setStatus(id, "paused")} disabled={!id || actingId === id} className="text-[11px] font-medium text-slate-500 hover:text-[#0F2440] disabled:opacity-40" aria-label={`Pause goal ${strOf(g?.title)}`}>Pause</button>
                        )}
                        {(filter === "paused") && (
                          <button onClick={() => id && setStatus(id, "active")} disabled={!id || actingId === id} className="text-[11px] font-medium text-blue-700 hover:underline disabled:opacity-40" aria-label={`Resume goal ${strOf(g?.title)}`}>Resume</button>
                        )}
                        <button onClick={() => id && setStatus(id, "completed")} disabled={!id || actingId === id} className="text-[11px] font-medium text-emerald-700 hover:underline disabled:opacity-40" aria-label={`Complete goal ${strOf(g?.title)}`}>
                          {actingId === id ? "…" : "Complete"}
                        </button>
                        <button onClick={() => id && deleteGoal(id)} disabled={!id || actingId === id} className="text-[11px] font-medium text-rose-600 hover:underline disabled:opacity-40" aria-label={`Delete goal ${strOf(g?.title)}`}>Delete</button>
                      </div>
                    )}
                  </div>
                </div>
              </Card>
            );
          })}
          <Card className="p-4 flex items-center gap-3 flex-wrap">
            <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-blue-50 text-blue-700"><Target size={15} /></span>
            <div className="flex-1 min-w-40">
              <p className="text-[13px] font-semibold text-[#0F2440]">Set a new goal</p>
              <p className="text-[11px] text-slate-500">Define a target, track progress, and let ARIA help you stay on track.</p>
            </div>
            <button onClick={() => setShowForm(true)} className={btnPrimary} aria-label="Create another goal"><Plus size={13} /> Create Goal</button>
          </Card>
        </div>
      )}
    </div>
  );
}

/* =====================================================================
   WHAT-IF
   ===================================================================== */

function WhatIfTab() {
  const [meta, setMeta] = useState<any>(null);
  const [metaLoading, setMetaLoading] = useState(true);
  const [metaError, setMetaError] = useState("");
  const [metaId, setMetaId] = useState("");
  const [variable, setVariable] = useState("");
  const [changeType, setChangeType] = useState("");
  const [changeValue, setChangeValue] = useState<number>(10);
  const [applyTo, setApplyTo] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [errorId, setErrorId] = useState("");
  const [saved, setSaved] = useState<any[]>([]);

  const variables: string[] = useMemo(() => asList(meta?.variables).map((v) => strOf(typeof v === "string" ? v : v?.name || v?.label)).filter(Boolean), [meta]);
  const changeTypes: string[] = useMemo(() => asList(meta?.change_types ?? meta?.changeTypes).map((v) => strOf(typeof v === "string" ? v : v?.name || v?.label)).filter(Boolean), [meta]);
  const applyTargets: string[] = useMemo(() => asList(meta?.apply_targets ?? meta?.applyTargets ?? meta?.scopes).map((v) => strOf(typeof v === "string" ? v : v?.name || v?.label)).filter(Boolean), [meta]);
  const range = useMemo(() => {
    const r = meta?.ranges?.[variable] ?? meta?.ranges?.[humanize(variable)] ?? meta?.range ?? null;
    if (!r || typeof r !== "object") return null;
    const min = numOf(r?.min ?? r?.minimum);
    const max = numOf(r?.max ?? r?.maximum);
    const step = numOf(r?.step) ?? 1;
    if (min === null || max === null) return null;
    return { min, max, step };
  }, [meta, variable]);

  const loadMeta = useCallback(async () => {
    setMetaLoading(true);
    setMetaError("");
    setMetaId("");
    try {
      const r = await intelligenceApi.getWhatIfMeta();
      setMeta(r.data || null);
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setMetaError(norm.message);
      setMetaId(norm.requestId);
      setMeta(null);
    } finally {
      setMetaLoading(false);
    }
  }, []);
  useEffect(() => { loadMeta(); }, [loadMeta]);

  useEffect(() => {
    if (!variable && variables.length) setVariable(variables[0]);
    if (!changeType && changeTypes.length) setChangeType(changeTypes[0]);
    if (!applyTo && applyTargets.length) setApplyTo(applyTargets[0]);
  }, [variables, changeTypes, applyTargets, variable, changeType, applyTo]);

  useEffect(() => {
    if (range) setChangeValue((v) => Math.max(range.min, Math.min(range.max, v)));
  }, [range]);

  const loadSaved = useCallback(async () => {
    try {
      const r = await intelligenceApi.listScenarios({ page_size: 6, sort: "recent" });
      setSaved(asList(r.data));
    } catch { /* non-fatal */ }
  }, []);
  useEffect(() => { loadSaved(); }, [loadSaved]);

  const [saveMsg, setSaveMsg] = useState("");
  const saveCurrentScenario = async () => {
    if (!result || !variable) return;
    setSaveMsg("");
    try {
      await intelligenceApi.saveScenario({ variable, change_type: changeType, change_value: changeValue, apply_to: applyTo, title: `${humanize(variable)} ${changeValue}%`, result });
      setSaveMsg("Scenario saved below.");
      loadSaved();
    } catch (e: any) {
      setSaveMsg(businessError(e?.message) || "ARIA couldn't save this scenario.");
    }
  };

  const loadSavedScenario = (s: any) => {
    if (strOf(s?.variable)) setVariable(strOf(s.variable));
    if (numOf(s?.change_value) !== null) setChangeValue(numOf(s.change_value) as number);
    if (strOf(s?.change_type)) setChangeType(strOf(s.change_type));
    if (strOf(s?.apply_to)) setApplyTo(strOf(s.apply_to));
    setTimeout(() => runScenario(), 120);
  };

  const deleteSavedScenario = async (id: string) => {
    if (!id) return;
    try {
      await intelligenceApi.deleteScenario(id);
      loadSaved();
    } catch { /* non-fatal */ }
  };

  const runScenario = async () => {
    setRunning(true);
    setError("");
    setErrorId("");
    setResult(null);
    try {
      /* Results come ONLY from POST /api/intelligence/what-if/run. */
      const r = await intelligenceApi.runWhatIf({ variable, change_type: changeType, change_value: changeValue, apply_to: applyTo });
      setResult(r.data || null);
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setError(norm.message);
      setErrorId(norm.requestId);
    } finally {
      setRunning(false);
    }
  };

  const impacts: any[] = asList(result?.projected_impact || result?.impacts || result?.kpis);
  const compSeries = useMemo(() => {
    const raw = asList(result?.revenue_comparison || result?.comparison_series || result?.comparison || result?.chart?.data);
    return raw.slice(0, 24).map((p: any, i: number) => ({
      label: strOf(p?.label || p?.period || `P${i + 1}`),
      baseline: numOf(p?.baseline ?? p?.base ?? p?.current) ?? 0,
      scenario: numOf(p?.scenario ?? p?.projected ?? p?.value),
    }));
  }, [result]);
  const compTitle = strOf(result?.comparison_title || "Revenue Comparison", "Revenue Comparison");
  const summary = strOf(result?.scenario_summary || result?.summary || "");
  const assumptions: string[] = asList(result?.assumptions).map((a) => strOf(typeof a === "string" ? a : a?.text)).filter(Boolean);

  if (metaLoading) return <LoadingPanel label="Loading scenario options…" />;
  if (metaError) return <ErrorPanel message={metaError} requestId={metaId} onRetry={loadMeta} />;
  if (!meta || (variables.length === 0 && changeTypes.length === 0)) {
    return <EmptyPanel icon={SlidersHorizontal} title="No scenario variables available." body="ARIA couldn't identify supported scenario variables for this dataset, so there is nothing meaningful to model yet." action={<button onClick={loadMeta} className="text-xs font-semibold text-blue-700 hover:underline">Retry</button>} />;
  }

  const resetScenario = () => { setResult(null); setError(""); setErrorId(""); setChangeValue(10); };
  return (
    <div className="space-y-4">
      <div className="text-[11px] text-slate-400 flex items-center gap-1">
        <span>Intelligence</span><ChevronRight size={11} /><span className="text-slate-600 font-medium">What-If</span>
      </div>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-[16px] font-semibold text-[#0F2440] tracking-tight">What-If Scenario Analysis</h3>
          <p className="text-[12px] text-slate-500">Explore how changes in key factors may impact your business.</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={saveCurrentScenario} disabled={!result} className={btnGhost} aria-label="Save scenario">Save Scenario</button>
          <button onClick={resetScenario} className={btnGhost} aria-label="Reset scenario"><RotateCcw size={13} /> Reset</button>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-4 md:p-5">
          <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Scenario Setup</h3>
          <div className="mt-3 space-y-3">
            <Field label="Variable to change" htmlFor="wi-var">
              <select id="wi-var" value={variable} onChange={(e) => setVariable(e.target.value)} className={selectCls} aria-label="Scenario variable">
                {variables.map((v) => <option key={v} value={v}>{humanize(v)}</option>)}
              </select>
            </Field>
            <Field label="Change Type" htmlFor="wi-type">
              <select id="wi-type" value={changeType} onChange={(e) => setChangeType(e.target.value)} className={selectCls} aria-label="Change type">
                {changeTypes.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
              </select>
            </Field>
            <div>
              <label htmlFor="wi-value" className="block text-[11px] font-medium text-slate-500 mb-1">
                Change Value{range ? ` (supported range ${range.min} to ${range.max})` : ""}
              </label>
              {range ? (
                <div className="flex items-center gap-2">
                  <input id="wi-value" type="range" min={range.min} max={range.max} step={range.step} value={changeValue}
                    onChange={(e) => setChangeValue(Number(e.target.value))} className="flex-1 accent-blue-700" aria-label="Change value slider" />
                  <span className="text-[12.5px] font-semibold text-[#0F2440] tabular-nums w-14 text-right">{changeValue}%</span>
                </div>
              ) : (
                <input id="wi-value" type="number" value={changeValue} onChange={(e) => setChangeValue(Number(e.target.value) || 0)} className={inputCls} aria-label="Change value" />
              )}
              {range && (changeValue < range.min || changeValue > range.max) && (
                <p className="text-[11px] text-amber-600 mt-1">Outside the supported range — results may be less reliable.</p>
              )}
            </div>
            <fieldset>
              <legend className="text-[11px] font-medium text-slate-500 mb-1.5">Apply to</legend>
              <div className="space-y-1.5" role="radiogroup" aria-label="Apply scenario to">
                {applyTargets.map((t) => (
                  <label key={t} className="flex items-center gap-2 text-[12.5px] text-[#0F2440] cursor-pointer">
                    <input type="radio" name="wi-apply" checked={applyTo === t} onChange={() => setApplyTo(t)} className="accent-blue-700" />
                    {humanize(t)}
                  </label>
                ))}
              </div>
            </fieldset>
            <button onClick={runScenario} disabled={running || !variable} className={`${btnPrimary} w-full`} aria-label="Run scenario">
              {running ? "Running…" : "Run Scenario"} <Play size={13} />
            </button>
          </div>
        </Card>

        <div className="lg:col-span-2 space-y-4">
          {running && <LoadingPanel label="Modeling scenario…" />}
          {!running && error && <ErrorPanel message={error} requestId={errorId} onRetry={runScenario} retryLabel="Run again" />}
          {!running && !error && !result && (
            <EmptyPanel icon={SlidersHorizontal} title="No scenario yet." body="Choose a variable, set a change, and run the scenario. ARIA models the outcome from your historical data." />
          )}
          {!running && !error && result && (
            <>
              <Card className="p-4 md:p-5">
                <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Projected Impact</h3>
                {impacts.length ? (
                  <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2">
                    {impacts.map((k: any, i: number) => (
                      <div key={i} className="rounded-xl border border-slate-200 p-3">
                        <p className="text-[11px] text-slate-500">{strOf(k?.label || k?.metric || `Impact ${i + 1}`)}</p>
                        <p className="text-[20px] font-semibold text-[#0F2440] tabular-nums mt-0.5">{k?.display || (numOf(k?.value) !== null ? fmtBiz(numOf(k.value)) : "—")}</p>
                        {strOf(k?.delta || k?.change_note) && <p className="text-[11px] text-slate-500 mt-0.5">{strOf(k.delta || k.change_note)}</p>}
                      </div>
                    ))}
                  </div>
                ) : <p className="text-[12px] text-slate-400 mt-2">The backend returned no projected impact figures.</p>}
              </Card>
              <Card className="p-4 md:p-5">
                <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">{compTitle}</h3>
                {compSeries.length ? (
                  <div className="h-[220px] mt-2">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={compSeries} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
                        <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} minTickGap={16} />
                        <YAxis tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} width={52} tickFormatter={(v: number) => fmtBiz(v)} />
                        <Tooltip formatter={(v: any, name: any) => [fmtMetric(numOf(v), variable), humanize(String(name))]} />
                        <Legend wrapperStyle={{ fontSize: 11 }} />
                        <Bar dataKey="baseline" name="Baseline" fill="#C7D6E8" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="scenario" name={`Scenario (${changeValue >= 0 ? "+" : ""}${changeValue}%)`} fill="#4F46E5" radius={[4, 4, 0, 0]}>
                          {compSeries.map((_, i) => <Cell key={i} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                ) : <p className="text-[12px] text-slate-400 mt-2">The backend returned no comparison series.</p>}
              </Card>
              {(summary || assumptions.length > 0) && (
                <Card className="p-4 md:p-5">
                  <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Scenario Summary</h3>
                  {summary && <p className="text-[12.5px] text-slate-700 leading-relaxed mt-2">{summary}</p>}
                  {assumptions.length > 0 && (
                    <ul className="mt-2 space-y-1">
                      {assumptions.map((a, i) => <li key={i} className="text-[11.5px] text-slate-500 leading-relaxed">· {a}</li>)}
                    </ul>
                  )}
                  <p className="mt-2 text-[11px] text-slate-400">This is a scenario estimate based on your historical data. Actual results may vary.</p>
                  <div className="mt-3 flex items-center gap-2">
                    <button onClick={saveCurrentScenario} className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12px] font-semibold text-blue-700 border border-blue-200 hover:bg-blue-50" aria-label="Save scenario">
                      <Save size={13} /> Save Scenario
                    </button>
                    {saveMsg && <span className="text-[11.5px] text-slate-600" role="status">{saveMsg}</span>}
                  </div>
                </Card>
              )}
            </>
          )}
        </div>
      </div>

      <Card className="p-4 md:p-5">
        <CardHead title="Saved Scenarios" sub="Scenarios you kept for later." right={<button onClick={loadSaved} className="text-[11px] font-semibold text-blue-700 hover:underline">View all</button>} />
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
          {saved.length === 0 && <p className="text-[12px] text-slate-400">No saved scenarios yet.</p>}
          {saved.map((s: any, i: number) => (
            <div key={strOf(s?.id || i)} className="rounded-xl border border-slate-200 p-3 flex items-center gap-2">
              <SlidersHorizontal size={14} className="text-indigo-600 flex-shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] font-medium text-[#0F2440] truncate">{strOf(s?.title || s?.name || `${humanize(strOf(s?.variable))} ${strOf(s?.change_value)}%`)}</p>
                <p className="text-[11px] text-slate-400">{strOf(s?.created_at || "")}</p>
              </div>
              <button onClick={() => loadSavedScenario(s)} className="text-[11px] font-semibold text-blue-700 hover:underline" aria-label={`Reload scenario ${strOf(s?.title || "")}`}>Load</button>
              {strOf(s?.id) && <button onClick={() => deleteSavedScenario(strOf(s.id))} className="text-[11px] font-medium text-slate-400 hover:text-rose-600" aria-label={`Delete scenario ${strOf(s?.title || "")}`}>Delete</button>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* =====================================================================
   REPORTS
   ===================================================================== */

const FALLBACK_SECTIONS = ["Executive Summary", "Key Metrics", "Analysis & Charts", "Insights", "Hypotheses", "Forecast", "Goals", "What-If Scenarios", "Recommendations"];

function ReportsTab({ meta }: { meta: any }) {
  const [templates, setTemplates] = useState<any[]>([]);
  const [tplLoading, setTplLoading] = useState(true);
  const [tplError, setTplError] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [dateRange, setDateRange] = useState("");
  const [sections, setSections] = useState<string[]>([]);
  const [genBusy, setGenBusy] = useState(false);
  const [genError, setGenError] = useState("");
  const [genOk, setGenOk] = useState("");
  const [actMsg, setActMsg] = useState("");
  const [reports, setReports] = useState<any[]>([]);
  const [repLoading, setRepLoading] = useState(false);

  const loadReports = useCallback(async () => {
    setRepLoading(true);
    try {
      const r = await intelligenceApi.listReports();
      setReports(asList(r.data));
    } catch { /* non-fatal */ }
    finally { setRepLoading(false); }
  }, []);
  useEffect(() => { loadReports(); }, [loadReports]);

  const deleteReport = async (id: string) => {
    if (!id) return;
    try {
      await intelligenceApi.deleteReport(id);
      loadReports();
    } catch (e: any) {
      setActMsg(businessError(e?.message) || "ARIA couldn't delete this report.");
    }
  };

  const viewReport = async (id: string) => {
    if (!id) return;
    try {
      const r = await intelligenceApi.getReport(id);
      const d: any = r.data || {};
      if (strOf(d?.name)) setName(strOf(d.name));
      if (strOf(d?.description)) setDescription(strOf(d.description));
      if (strOf(d?.date_range)) setDateRange(strOf(d.date_range));
      const secs = asList(d?.sections).map((s) => strOf(typeof s === "string" ? s : s?.name || s?.label)).filter(Boolean);
      if (secs.length) setSections(secs);
      if (strOf(d?.template)) setTemplateId(strOf(d.template));
      setGenOk(`Loaded report ${strOf(d?.name || "")}. Review and Generate PDF to re-export.`);
    } catch (e: any) {
      setGenError(businessError(e?.message) || "ARIA couldn't open this report.");
    }
  };

  const dateRanges: string[] = useMemo(() => {
    const d = meta?.date_ranges ?? meta?.dateRanges ?? [];
    return asList(d).map((x) => strOf(typeof x === "string" ? x : x?.name || x?.label)).filter(Boolean);
  }, [meta]);

  const loadTemplates = useCallback(async () => {
    setTplLoading(true);
    setTplError("");
    try {
      const r = await intelligenceApi.listReportTemplates();
      const list = asList(r.data);
      setTemplates(list);
      if (list.length && !templateId) {
        const first = list[0];
        setTemplateId(strOf(first?.id || first?.name));
        const secs = asList(first?.sections).map((s) => strOf(typeof s === "string" ? s : s?.name || s?.label)).filter(Boolean);
        if (secs.length) setSections(secs);
      }
    } catch (e: any) {
      setTplError(businessError(e?.message) || "ARIA couldn't load report templates.");
    } finally {
      setTplLoading(false);
    }
  }, [templateId]);
  useEffect(() => { loadTemplates(); }, [loadTemplates]);

  useEffect(() => {
    if (!dateRange && dateRanges.length) setDateRange(dateRanges[0]);
    if (sections.length === 0) setSections(FALLBACK_SECTIONS.slice(0, 9));
  }, [dateRanges, dateRange, sections.length]);

  const activeTemplate = templates.find((t) => strOf(t?.id || t?.name) === templateId) || null;
  const toggleSection = (s: string) => setSections((prev) => (prev.includes(s) ? prev.filter((x) => x !== s) : [...prev, s]));

  const pickTemplate = (id: string) => {
    setTemplateId(id);
    const t = templates.find((x) => strOf(x?.id || x?.name) === id);
    const secs = asList(t?.sections).map((s) => strOf(typeof s === "string" ? s : s?.name || s?.label)).filter(Boolean);
    if (secs.length) setSections(secs);
  };

  const generatePdf = async () => {
    setGenBusy(true);
    setGenError("");
    setGenOk("");
    try {
      await intelligenceApi.generateReport({ name: name || undefined, description: description || undefined, date_range: dateRange || undefined, sections, template: templateId || undefined });
      setGenOk("Report generated. Opening print view — choose Save as PDF.");
      loadReports();
      setTimeout(() => { try { window.print(); } catch { /* ignore */ } }, 400);
    } catch (e: any) {
      setGenError(businessError(e?.message) || "ARIA couldn't generate this report.");
    } finally {
      setGenBusy(false);
    }
  };

  const reportAction = async (kind: "template" | "schedule" | "share" | "ppt") => {
    setActMsg("");
    try {
      if (kind === "template") {
        await intelligenceApi.saveReportTemplate({ name: name || "Untitled template", sections, template: templateId || undefined });
        setActMsg("Saved as a template.");
        loadTemplates();
      } else if (kind === "schedule") {
        await apiFetch("/intelligence/reports/schedule", { method: "POST", body: JSON.stringify({ name, date_range: dateRange, sections, template: templateId }) });
        setActMsg("Report scheduled.");
      } else if (kind === "share") {
        await apiFetch("/intelligence/reports/share", { method: "POST", body: JSON.stringify({ name, date_range: dateRange, sections, template: templateId }) });
        setActMsg("Share link created.");
      } else {
        await apiFetch("/intelligence/reports/export", { method: "POST", body: JSON.stringify({ format: "pptx", name, date_range: dateRange, sections, template: templateId }) });
        setActMsg("PowerPoint export started — check your downloads shortly.");
      }
    } catch (e: any) {
      setActMsg(businessError(e?.message) || "That action isn't available right now.");
    }
  };

  const hasDatasetRep = dateRanges.length > 0 || templates.length > 0;
  const scrollPreview = () => { try { document.getElementById("intel-report-preview")?.scrollIntoView({ behavior: "smooth", block: "start" }); } catch {} };
  return (
    <div className="space-y-4">
      <div className="text-[11px] text-slate-400 flex items-center gap-1">
        <span>Intelligence</span><ChevronRight size={11} /><span className="text-slate-600 font-medium">Reports</span>
      </div>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-[16px] font-semibold text-[#0F2440] tracking-tight">Report Builder</h3>
          <p className="text-[12px] text-slate-500">Create professional reports from your analysis.</p>
        </div>
        <div className="flex items-center gap-1.5">
          <button onClick={scrollPreview} className={btnGhost} aria-label="Preview report"><Eye size={13} /> Preview</button>
          <button onClick={generatePdf} disabled={genBusy} className={btnPrimary} aria-label="Generate PDF top"><Printer size={13} /> {genBusy ? "Generating..." : "Generate PDF"}</button>
        </div>
      </div>
      {!hasDatasetRep && !tplLoading && <NoDatasetPanel />}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="p-4 md:p-5">
          <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Report Details</h3>
          <div className="mt-3 space-y-3">
            <Field label="Report Name" htmlFor="rep-name">
              <input id="rep-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Q2 Business Review" className={inputCls} aria-label="Report name" />
            </Field>
            <Field label="Description (optional)" htmlFor="rep-desc">
              <input id="rep-desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this report covers…" className={inputCls} aria-label="Report description" />
            </Field>
            <Field label="Date Range" htmlFor="rep-range">
              <select id="rep-range" value={dateRange} onChange={(e) => setDateRange(e.target.value)} className={selectCls} aria-label="Report date range">
                {dateRanges.length === 0 && <option value="">Select…</option>}
                {dateRanges.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
              </select>
            </Field>
            <fieldset>
              <legend className="text-[11px] font-medium text-slate-500 mb-1.5">Include Sections</legend>
              <div className="space-y-1.5">
                {(activeTemplate && asList(activeTemplate?.sections).length
                  ? asList(activeTemplate.sections).map((s) => strOf(typeof s === "string" ? s : s?.name || s?.label)).filter(Boolean)
                  : [...new Set([...sections, ...FALLBACK_SECTIONS])].slice(0, 9)
                ).map((s) => (
                  <label key={s} className="flex items-center gap-2 text-[12.5px] text-[#0F2440] cursor-pointer">
                    <input type="checkbox" checked={sections.includes(s)} onChange={() => toggleSection(s)} className="accent-blue-700" aria-label={`Include ${s}`} />
                    {s}
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        </Card>

        <Card className="p-4 md:p-5">
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Report Preview</h3>
            <span className="text-[11px] text-slate-400">{sections.length > 0 ? `1 / ${sections.length}` : "No sections"}</span>
          </div>
          <div id="intel-report-preview" className="mt-3 rounded-xl border border-slate-200 bg-slate-50/60 p-5 min-h-64" aria-label="Report preview">
            <p className="text-[11px] font-bold tracking-[0.14em] text-blue-700">ARIA</p>
            <h4 className="text-[17px] font-semibold text-[#0F2440] tracking-tight mt-1">{name || "Business Review"}</h4>
            <p className="text-[11px] text-slate-500 mt-0.5">Insight. Analysis. Action.</p>
            {description && <p className="text-[12px] text-slate-600 mt-2 leading-relaxed">{description}</p>}
            <div className="mt-3 space-y-1.5">
              {sections.length === 0 && <p className="text-[11px] text-slate-400">Select sections on the left to preview the outline.</p>}
              {sections.map((s) => (
                <div key={s} className="flex items-center gap-2 text-[12px] text-slate-600">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-600" />{s}
                </div>
              ))}
            </div>
            <p className="mt-4 text-[10.5px] text-slate-400">Prepared {dateRange ? `for ${dateRange}` : "—"} · {activeTemplate ? humanize(strOf(activeTemplate?.name || templateId)) : "No template"}</p>
          </div>
          {genError && <p className="mt-2 text-[12px] text-rose-600" role="alert">{genError}</p>}
          {genOk && <p className="mt-2 text-[12px] text-emerald-700" role="status">{genOk}</p>}
          <button onClick={generatePdf} disabled={genBusy} className={`${btnPrimary} w-full mt-3`} aria-label="Generate PDF">
            <Printer size={13} /> {genBusy ? "Generating…" : "Generate PDF"}
          </button>
        </Card>

        <div className="space-y-4">
          <Card className="p-4 md:p-5">
            <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Template</h3>
            {tplLoading && <div className="skeleton h-9 rounded-lg mt-2" aria-hidden />}
            {!tplLoading && tplError && <p className="text-[12px] text-rose-600 mt-2" role="alert">{tplError}</p>}
            {!tplLoading && !tplError && (
              <div className="mt-2 space-y-1.5" role="radiogroup" aria-label="Report template">
                {templates.length === 0 && (
                  <div className="mt-2 space-y-1.5">
                    {[["Professional", "Clean and modern"], ["Executive", "Focused on key insights"], ["Detailed", "Comprehensive analysis"]].map(([n, d]) => (
                      <button key={n} onClick={() => { setTemplateId(n); }} className={`w-full text-left rounded-xl border p-2.5 transition-colors ${templateId === n ? "border-blue-500 bg-blue-50/60" : "border-slate-200 hover:border-slate-300"}`}>
                        <span className="block text-[12.5px] font-semibold text-[#0F2440]">{n}</span>
                        <span className="block text-[11px] text-slate-400 mt-0.5">{d}</span>
                      </button>
                    ))}
                  </div>
                )}
                {templates.map((t: any) => {
                  const id = strOf(t?.id || t?.name);
                  const on = templateId === id;
                  return (
                    <button key={id} role="radio" aria-checked={on} onClick={() => pickTemplate(id)}
                      className={`w-full text-left rounded-xl border p-2.5 transition-colors ${on ? "border-blue-500 bg-blue-50/60" : "border-slate-200 hover:border-slate-300"}`}>
                      <span className="block text-[12.5px] font-semibold text-[#0F2440]">{strOf(t?.name || id)}</span>
                      <span className="block text-[11px] text-slate-400 mt-0.5">{strOf(t?.description || "")}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </Card>
          <Card className="p-4 md:p-5">
            <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">Report Actions</h3>
            <div className="mt-2 space-y-1.5">
              {[
                { k: "template" as const, label: "Save as Template", Icon: Save },
                { k: "schedule" as const, label: "Schedule Report", Icon: CalendarDays },
                { k: "share" as const, label: "Share Report", Icon: Share2 },
                { k: "ppt" as const, label: "Export to PowerPoint", Icon: Download },
              ].map(({ k, label, Icon }) => (
                <button key={k} onClick={() => reportAction(k)} className="w-full flex items-center gap-2 text-left text-[12.5px] font-medium text-[#0F2440] hover:text-blue-700 rounded-lg px-2 py-1.5 hover:bg-blue-50/60 transition-colors" aria-label={label}>
                  <Icon size={13} className="text-slate-400" />{label}
                </button>
              ))}
            </div>
            {actMsg && <p className="mt-2 text-[11.5px] text-slate-600" role="status">{actMsg}</p>}
            <p className="mt-2 text-[11px] text-slate-400">Reports use verified outputs from your analyses, insights, forecasts and goals.</p>
          </Card>
        </div>
      </div>
      <Card className="p-4 md:p-5">
        <CardHead title="Generated Reports" sub="Every report you generate is kept here." right={repLoading ? <span className="text-[11px] text-slate-400">Loading…</span> : <button onClick={loadReports} className="text-[11px] font-semibold text-blue-700 hover:underline" aria-label="Refresh reports">Refresh</button>} />
        <div className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-2">
          {reports.length === 0 && <p className="text-[12px] text-slate-400">No reports yet — fill the details and choose Generate PDF.</p>}
          {reports.map((r: any, i: number) => (
            <div key={strOf(r?.id || i)} className="rounded-xl border border-slate-200 p-3 flex items-center gap-2">
              <FileText size={14} className="text-blue-600 flex-shrink-0" />
              <div className="min-w-0 flex-1">
                <p className="text-[12.5px] font-medium text-[#0F2440] truncate">{strOf(r?.name || "Report")}</p>
                <p className="text-[11px] text-slate-400">{strOf(r?.generated_at || r?.created_at || "")}{asList(r?.sections).length ? ` · ${asList(r.sections).length} sections` : ""}</p>
              </div>
              <button onClick={() => viewReport(strOf(r?.id))} disabled={!r?.id} className="text-[11px] font-semibold text-blue-700 hover:underline disabled:opacity-40" aria-label={`View report ${strOf(r?.name || "")}`}>View</button>
              {strOf(r?.id) && <button onClick={() => deleteReport(strOf(r.id))} className="text-[11px] font-medium text-slate-400 hover:text-rose-600" aria-label={`Delete report ${strOf(r?.name || "")}`}>Delete</button>}
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* =====================================================================
   PAGE
   ===================================================================== */

export default function Intelligence({
  connectionStatus = "not-connected",
  onAskCopilot,
}: {
  connectionStatus?: string;
  onAskCopilot?: (question: string) => void;
}) {
  const theme = useTheme() as any;
  const setPage = theme?.setPage;
  const [tab, setTab] = useState<IntelTab>(() => tabFromHash());
  const [meta, setMeta] = useState<any>(null);
  const [metaLoading, setMetaLoading] = useState(true);
  const [metaError, setMetaError] = useState("");
  const [metaId, setMetaId] = useState("");
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  const loadMeta = useCallback(async () => {
    setMetaLoading(true);
    setMetaError("");
    setMetaId("");
    try {
      const r = await intelligenceApi.getMeta();
      setMeta(r.data || null);
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setMetaError(norm.message);
      setMetaId(norm.requestId);
      setMeta(null);
    } finally {
      setMetaLoading(false);
    }
  }, []);
  useEffect(() => { if (connectionStatus === "connected") loadMeta(); else { setMeta(null); setMetaLoading(false); } }, [connectionStatus, loadMeta]);

  const goto = (t: IntelTab) => {
    setTab(t);
    try {
      const base = (window.location.hash || "#/intelligence").split("?")[0];
      window.location.hash = `${base}?tab=${t}`;
    } catch { /* ignore */ }
  };

  const ask = (q: string) => {
    const question = (q || "").trim();
    if (onAskCopilot) { onAskCopilot(question); return; }
    try {
      sessionStorage.setItem("aria_copilot_context", JSON.stringify({ origin: "intelligence", question }));
    } catch { /* best-effort */ }
    if (setPage) setPage("copilot");
  };

  const quickPrefill = (_actionId: string) => { /* quick actions drive Explore defaults in place */ };

  const onTabKey = (e: React.KeyboardEvent, idx: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    let next = idx;
    if (e.key === "ArrowRight") next = (idx + 1) % TABS.length;
    if (e.key === "ArrowLeft") next = (idx - 1 + TABS.length) % TABS.length;
    if (e.key === "Home") next = 0;
    if (e.key === "End") next = TABS.length - 1;
    goto(TABS[next].id);
    tabRefs.current[next]?.focus();
  };

  if (connectionStatus !== "connected") {
    return (
      <div className="min-h-full bg-white text-[#0F2440]">
        <div className="p-6 max-w-screen-xl mx-auto">
          <p className="text-[11px] font-bold tracking-[0.14em] text-blue-700">ARIA INTELLIGENCE</p>
          <h2 className="text-xl font-semibold tracking-tight">ARIA Intelligence</h2>
          <p className="text-sm text-slate-500 mt-0.5">Explore beyond the dashboard.</p>
          <div className="mt-8 text-center py-12 bg-white border border-slate-200 rounded-2xl shadow-sm">
            <Database size={22} className="mx-auto text-slate-400 mb-3" />
            <p className="text-sm font-medium">No data source connected</p>
            <p className="text-xs text-slate-500 mt-1">Connect PostgreSQL, MySQL, or upload a CSV to start analyzing with Intelligence.</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-full bg-white text-[#0F2440]">
      <div className="p-4 md:p-6 max-w-screen-xl mx-auto">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="min-w-0">
            <h2 className="text-[22px] font-bold tracking-tight">ARIA Intelligence</h2>
            <p className="text-[14px] font-medium mt-0.5">Explore beyond the dashboard.</p>
            <p className="text-[12px] text-slate-500 mt-0.5 max-w-xl">Investigate patterns, compare performance, test scenarios, and build business analysis from your connected data.</p>
          </div>
          <p className="hidden md:block text-[12px] text-slate-400 italic text-right leading-relaxed">
            &ldquo;Better questions.<br />Deeper understanding.<br />Stronger decisions.&rdquo;
          </p>
        </div>

        {/* Tab bar */}
        <div className="mt-4 flex items-center gap-1 border-b border-slate-200 overflow-x-auto" role="tablist" aria-label="Intelligence sections">
          {TABS.map(({ id, label, Icon }, i) => {
            const on = tab === id;
            return (
              <button
                key={id}
                ref={(el) => { tabRefs.current[i] = el; }}
                role="tab"
                aria-selected={on}
                aria-controls={`intel-panel-${id}`}
                id={`intel-tab-${id}`}
                tabIndex={on ? 0 : -1}
                onClick={() => goto(id)}
                onKeyDown={(e) => onTabKey(e, i)}
                className={`inline-flex items-center gap-1.5 px-3.5 py-2.5 text-[12.5px] font-medium border-b-2 -mb-px transition-colors whitespace-nowrap focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${on ? "border-blue-700 text-blue-800" : "border-transparent text-slate-400 hover:text-slate-600"}`}
              >
                <Icon size={14} /> {label}
              </button>
            );
          })}
        </div>

        {/* Meta-level failure still allows tab browsing of cached/empty states,
            but Explore/Goals/What-If/Reports need meta options to function. */}
        {metaLoading && (
          <div className="mt-4" aria-busy="true" aria-label="Loading intelligence options">
            <p className="sr-only">Loading intelligence options…</p>
            <Card><SkeletonBlock lines={2} /></Card>
          </div>
        )}
        {!metaLoading && metaError && (tab === "explore" || tab === "goals" || tab === "whatif" || tab === "reports") && !meta && (
          <div className="mt-4">
            <ErrorPanel message={metaError} requestId={metaId} onRetry={loadMeta} retryLabel="Reload options" />
          </div>
        )}

        <div id={`intel-panel-${tab}`} role="tabpanel" aria-labelledby={`intel-tab-${tab}`} className="mt-4">
          {tab === "explore" && <ExploreTab meta={meta || {}} onRunQuick={quickPrefill} onGoto={goto} onAsk={ask} />}
          {tab === "hypotheses" && <HypothesesTab onAsk={ask} />}
          {tab === "goals" && <GoalsTab meta={meta || {}} />}
          {tab === "whatif" && <WhatIfTab />}
          {tab === "reports" && <ReportsTab meta={meta || {}} />}
        </div>
      </div>
    </div>
  );
}
