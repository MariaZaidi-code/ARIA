import { useState, useEffect, useCallback, useMemo } from "react";
import { CheckCircle, Bookmark, MessageSquare, ChevronDown, ChevronUp, Loader2, RefreshCw, FlaskConical, TrendingUp, Database, AlertTriangle, Play } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Line } from "recharts";
import { useTheme } from "../App";
import { ChartFrame, BizTooltip } from "../components/charts";

/* =====================================================================
   ARIA Prescription — evidence-based decision/action workspace (pres.docx).
   ACTION layer: Insights (what) → Hypothesis (why, supported?) → Forecast
   (next) → Prescription (what to consider doing). Only recommends when
   evidence justifies it; otherwise refuses with alternatives (§23).
   Trust labels (§33): OBSERVED / MODELLED / SIMULATED / PREDICTED.
   ===================================================================== */

interface PrescriptionProps {
  insightResult?: any;
  connectionStatus?: string;
  onAskQuestion?: (question: string) => void;
}

type Status = "idle" | "loading" | "done" | "empty" | "error";

const LOAD_STAGES = [
  "Validating evidence…",
  "Identifying drivers…",
  "Evaluating possible actions…",
  "Modeling scenarios…",
  "Comparing outcomes…",
  "Assessing risk…",
  "Ranking recommendations…",
  "Preparing decision…",
];

const ERROR_MAP: Record<string, { title: string; hint: string }> = {
  NO_CONNECTION: { title: "No data source connected", hint: "Connect PostgreSQL, MySQL, or upload a CSV to generate evidence-based actions." },
  INVALID_METRIC: { title: "Choose a target metric first", hint: "ARIA won't guess what to improve — pick the metric this decision is about." },
  INVALID_DRIVER: { title: "Driver not usable", hint: "ARIA couldn't find that field. Pick a driver from the available fields." },
  INSUFFICIENT_DATA: { title: "Not enough reliable observations", hint: "ARIA cannot model an intervention from this sample." },
  INSUFFICIENT_HISTORY: { title: "Not enough history", hint: "Scenario modeling needs a longer track record." },
  SCENARIO_UNSUPPORTED: { title: "Scenario not supported", hint: "Adjust the scenario to stay within modeled ranges (±50%, numeric driver, equals segments)." },
  ANALYSIS_FAILED: { title: "Analysis could not be completed", hint: "Your data was not changed. Try again." },
  MODEL_FAILED: { title: "Model could not be fitted", hint: "The fields aren't modelable together. Try a different driver." },
  LLM_FAILED: { title: "Explanation unavailable", hint: "The numbers stand — only ARIA's wording service is down." },
  TIMEOUT: { title: "Analysis timed out", hint: "Narrow the question and try again." },
  INTERNAL_ERROR: { title: "Something went wrong", hint: "Your data was not changed. Try again." },
};

const fmtK = (v: any) => {
  if (v === null || v === undefined || isNaN(Number(v))) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
};

const riskStyle: Record<string, string> = {
  low: "text-positive bg-positive/10 border-positive/20",
  medium: "text-warning bg-warning/10 border-warning/20",
  high: "text-negative bg-negative/10 border-negative/20",
};

function Tag({ children, tone }: { children: any; tone: string }) {
  return <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide ${tone}`}>{children}</span>;
}

export default function Prescription({ insightResult = null, connectionStatus = "not-connected", onAskQuestion }: PrescriptionProps) {
  const { isDark, setPage } = useTheme() as any;
  const [status, setStatus] = useState<Status>("idle");
  const [stage, setStage] = useState(0);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [ctx, setCtx] = useState<any>(null);
  const [origin, setOrigin] = useState<any>(null);
  const [metric, setMetric] = useState("");
  const [driver, setDriver] = useState("");
  const [question, setQuestion] = useState("What should we do about it?");
  const [analysis, setAnalysis] = useState<any>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [saved, setSaved] = useState<any[]>([]);
  const [fetchedAt, setFetchedAt] = useState("");
  // custom scenario playground per expanded card
  const [simPct, setSimPct] = useState<number>(-10);
  const [simResult, setSimResult] = useState<any>(null);
  const [simLoading, setSimLoading] = useState(false);

  const authHeader = () => {
    const token = localStorage.getItem("aria_auth_token");
    return { Authorization: `Bearer ${token}` };
  };

  /* ---- Intake (§5): structured handoffs from Insights/Hypothesis/Forecast ---- */
  useEffect(() => {
    try {
      const raw = sessionStorage.getItem("aria_insight_handoff") || sessionStorage.getItem("aria_forecast_prefill");
      if (raw) {
        const h = JSON.parse(raw);
        sessionStorage.removeItem("aria_insight_handoff");
        sessionStorage.removeItem("aria_forecast_prefill");
        setOrigin({ origin: h.origin || "insight", metric: h.metric, driver: h.driver, segment: h.segment || h.dimensions?.[0] });
        if (h.metric) setMetric(typeof h.metric === "string" ? h.metric.split(" (")[0] : "");
        if (h.driver) setDriver(typeof h.driver === "string" ? h.driver : "");
        if (h.question) setQuestion(`What should we do about: ${h.question}`.slice(0, 200));
      }
    } catch { /* best-effort */ }
    if (connectionStatus === "connected") {
      fetchContext();
      fetchSaved();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionStatus]);

  const fetchContext = useCallback(async () => {
    try {
      const res = await fetch("/api/prescriptions/context", { headers: authHeader() });
      const data = await res.json();
      if (data.ok) {
        setCtx(data);
        setMetric((m) => m || data.metrics?.[0]?.column || "");
      }
    } catch { /* optional */ }
  }, []);

  const fetchSaved = useCallback(async () => {
    try {
      const res = await fetch("/api/prescriptions/saved", { headers: authHeader() });
      const data = await res.json();
      if (data.ok) setSaved(data.saved || []);
    } catch { /* optional */ }
  }, []);

  const failWith = (data: any) => {
    const code = data?.code || "ANALYSIS_FAILED";
    setErrorCode(code);
    setError(data?.detail || "");
    setAnalysis(null);
    setStatus(data?.status === "no_prescription" ? "empty" : "error");
    if (data?.status === "no_prescription") setAnalysis(data);
  };

  const isDoc = !!(ctx && ctx.document);
  const generate = useCallback(async (m?: string, d?: string) => {
    const useMetric = m ?? metric;
    const useDriver = d ?? driver;
    if (!useMetric && !isDoc) {
      setErrorCode("INVALID_METRIC"); setError(""); setStatus("error"); return;
    }
    setStatus("loading"); setStage(0); setError(""); setErrorCode("");
    setAnalysis(null); setSimResult(null);
    const timer = setInterval(() => setStage((s) => Math.min(s + 1, LOAD_STAGES.length - 1)), 1100);
    try {
      const seg = origin?.segment && typeof origin.segment === "object" ? origin.segment : undefined;
      const res = await fetch("/api/prescriptions/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({
          metric: useMetric || undefined, driver: useDriver || undefined,
          dimensions: seg?.field ? [seg.field] : undefined,
          segment: seg,
          question,
          context: origin ? { origin: origin.origin, metric: useMetric, driver: useDriver || undefined } : undefined,
        }),
      });
      const data = await res.json();
      clearInterval(timer);
      if (data.status === "no_prescription") { failWith(data); return; }
      if (!data.ok && !data.success) { failWith(data); return; }
      setAnalysis(data);
      setFetchedAt(new Date().toISOString());
      const rec = (data.prescriptions || []).find((p: any) => p.scenario_label === "recommended") || data.prescriptions?.[0];
      if (rec) { setExpandedId(rec.id); setSimPct(Number(rec.impact?.driver_pct ?? -10)); }
      setStatus("done");
    } catch (e: any) {
      clearInterval(timer);
      setErrorCode("ANALYSIS_FAILED"); setError(e?.message || ""); setStatus("error");
    }
  }, [metric, driver, question, origin]);

  const runScenario = useCallback(async (rx: any, pct: number) => {
    if (!analysis) return;
    setSimLoading(true);
    try {
      const seg = rx?.evidence?.segment;
      const res = await fetch("/api/prescriptions/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({
          table: analysis.table, metric: analysis.metric, driver: analysis.driver,
          changes: [{ field: analysis.driver, operation: "percent", value: pct }],
          filters: seg?.field ? [{ field: seg.field, operator: "equals", value: seg.value }] : [],
          join: analysis.join_ref || undefined,
        }),
      });
      const data = await res.json();
      if (data.ok && data.scenarios?.length) setSimResult(data.scenarios[0]);
      else setSimResult({ error: data.detail || "Scenario not supported." });
    } catch (e: any) {
      setSimResult({ error: e?.message || "Scenario failed." });
    } finally {
      setSimLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [analysis]);

  const saveRx = async (rx: any) => {
    try {
      const res = await fetch("/api/prescriptions/save", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ prescription: rx, question }),
      });
      const data = await res.json();
      if (data.ok) setSaved(data.saved || []);
    } catch { /* non-fatal */ }
  };

  const deleteSaved = async (id: string) => {
    try {
      const res = await fetch(`/api/prescriptions/saved/${id}`, { method: "DELETE", headers: authHeader() });
      const data = await res.json();
      if (data.ok) setSaved(data.saved || []);
    } catch { /* non-fatal */ }
  };

  const prescriptions: any[] = analysis?.prescriptions || [];
  const top = prescriptions[0];
  const multiTable = useMemo(() => new Set((ctx?.metrics || []).map((m: any) => m.table)).size > 1, [ctx]);
  const metricTable = useMemo(() => (ctx?.metrics || []).find((m: any) => m.column === metric)?.table, [ctx, metric]);
  // Drivers: numerics (same table or declared-join tables) plus derived
  // ones like stay length — all from the live schema context, never static.
  const driverOptions = useMemo(() => (ctx?.drivers || []).filter((d: any) =>
    (d.kind === "numeric" || d.kind === "derived") && !(d.column === metric && d.table === metricTable)
  ), [ctx, metric, metricTable]);
  const errInfo = ERROR_MAP[errorCode] || ERROR_MAP.ANALYSIS_FAILED;
  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  const trendLine = useMemo(() => {
    const viz = analysis?.evidence_viz;
    if (!viz || !viz.points?.length || !viz.trend) return null;
    const xs = viz.points.map((p: any) => Number(p.x)).filter((v: number) => !isNaN(v));
    if (!xs.length) return null;
    const lo = Math.min(...xs), hi = Math.max(...xs);
    const { slope, intercept } = viz.trend;
    return [{ x: lo, y: slope * lo + intercept }, { x: hi, y: slope * hi + intercept }];
  }, [analysis]);

  const goHypothesis = (rx: any) => {
    const drv = rx?.evidence?.driver || analysis?.driver;
    try {
      sessionStorage.setItem("aria_hypothesis_prefill", JSON.stringify({
        metric: analysis.metric, driver: drv,
        question: rx?.action_type === "investigate"
          ? `Does ${analysis.metric} truly differ across ${drv}, and what drives it?`
          : `Run a controlled hypothesis test comparing ${drv} and ${analysis.metric} response.`,
        source: { tables: [analysis.table] },
      }));
    } catch {}
    (setPage as any)?.("hypothesis");
  };

  /* ---- NO_SOURCE: never fake prescriptions ---- */
  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto space-y-4">
        <h2 className="text-xl font-bold text-foreground tracking-tight">Prescription</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Turn ARIA's validated findings into evidence-based actions.</p>
        <div className="text-center py-12 bg-card border border-border rounded-xl">
          <Database size={22} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">Connect a data source to evaluate interventions</p>
          <button onClick={() => (setPage as any)?.("data")} className="mt-3 text-xs font-semibold text-primary hover:underline">Go to Data Sources</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 max-w-[1400px] mx-auto space-y-4">
      {/* Header (§31) */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-xl font-bold text-foreground tracking-tight">Prescription</h2>
          <p className="text-[13px] text-muted-foreground mt-0.5">Turn ARIA's validated findings into evidence-based actions.</p>
          <div className="mt-1.5 flex items-center gap-2 text-[11px] text-muted-foreground flex-wrap">
            <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-positive inline-block" />{ctx?.connection?.db_name || "Connected source"}</span>
            {origin?.origin && <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-medium">from {origin.origin}</span>}
            {origin?.metric && <span>· {String(origin.metric).split(" (")[0]}</span>}
            {fetchedAt && <span>· analyzed {new Date(fetchedAt).toLocaleTimeString()}</span>}
          </div>
        </div>
        <button onClick={() => generate()} className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors">
          <RefreshCw size={13} /> Refresh Analysis
        </button>
      </div>

      {/* Intake: question + evidence-backed selectors (or document question) */}
      <div className="bg-card border border-border rounded-xl p-4 space-y-3">
        {isDoc ? (
          <div className="flex flex-col sm:flex-row gap-2">
            <input value={question} onChange={(e) => setQuestion(e.target.value)}
              placeholder="What decision should this document inform? e.g. What risks need action?"
              className="flex-1 bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
            <button onClick={() => generate()} disabled={status === "loading" || !question.trim()}
              className="inline-flex items-center gap-1.5 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50 whitespace-nowrap">
              <Play size={13} /> Analyze document
            </button>
          </div>
        ) : (
        <div className="grid grid-cols-1 md:grid-cols-[1fr_180px_180px_auto] gap-2">
          <input value={question} onChange={(e) => setQuestion(e.target.value)}
            placeholder="What should we do about it?"
            className="bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-primary" />
          <select value={metric} onChange={(e) => { setMetric(e.target.value); setDriver(""); }} className="bg-secondary border border-border rounded-lg px-2 py-2 text-xs text-foreground" aria-label="Target metric">
            <option value="">Target metric…</option>
            {(ctx?.metrics || []).map((m: any) => <option key={`${m.table}.${m.column}`} value={m.column}>{m.column.replace(/_/g, " ")}{multiTable ? ` (${m.table})` : ""}</option>)}
          </select>
          <select value={driver} onChange={(e) => setDriver(e.target.value)} className="bg-secondary border border-border rounded-lg px-2 py-2 text-xs text-foreground" aria-label="Driver (optional)">
            <option value="">Auto driver…</option>
            {driverOptions.map((d: any) => <option key={`${d.table}.${d.column}`} value={d.column}>{d.kind === "derived" ? `Length of stay (from dates)` : d.column.replace(/_/g, " ")}{multiTable ? ` (${d.table})` : ""}{d.note ? ` — ${d.note}` : ""}</option>)}
          </select>
          <button onClick={() => generate()} disabled={status === "loading" || !metric}
            className="inline-flex items-center gap-1.5 bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50 whitespace-nowrap">
            <Play size={13} /> Evaluate
          </button>
        </div>
        )}
        {(ctx?.opportunities?.length > 0) && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground mr-1">Worth testing:</span>
            {ctx.opportunities.slice(0, 6).map((o: any, i: number) => (
              <button key={i} onClick={() => { setMetric(o.metric); setDriver(o.driver === "length_of_stay" ? "" : o.driver); setTimeout(() => generate(o.metric, o.driver === "length_of_stay" ? "" : o.driver), 60); }}
                className="text-[11px] px-2 py-1 rounded-full border border-border text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors">
                {String(o.metric).replace(/_/g, " ")} ← {o.driver === "length_of_stay" ? "stay length" : String(o.driver).replace(/_/g, " ")}
              </button>
            ))}
          </div>
        )}
        {(ctx?.table_limitations?.length > 0) && (
          <div className="space-y-0.5">
            {(ctx.table_limitations || []).slice(0, 3).map((l: string, i: number) => (
              <p key={i} className="text-[11px] text-warning">· {l}</p>
            ))}
          </div>
        )}
      </div>

      {/* Loading stages (§30) */}
      {status === "loading" && (
        <div className="bg-card border border-border rounded-xl p-6 flex flex-col items-center gap-3">
          <Loader2 size={22} className="animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">{LOAD_STAGES[stage]}</p>
        </div>
      )}

      {/* Error (mapped codes, never blank) */}
      {status === "error" && (
        <div className="bg-card border border-warning/40 rounded-xl p-4 space-y-1.5">
          <p className="text-sm font-semibold text-foreground">{errInfo.title}</p>
          <p className="text-sm text-muted-foreground">{error || errInfo.hint}</p>
          <div className="flex gap-2 pt-1">
            <button onClick={() => generate()} className="text-xs font-semibold text-primary hover:underline">Try again</button>
            {onAskQuestion && <button onClick={() => onAskQuestion(`How should I act on ${metric || "my data"}?`)} className="text-xs text-muted-foreground hover:text-foreground">Ask ARIA</button>}
          </div>
        </div>
      )}

      {/* Refusal (§23): no invented recommendation + alternatives */}
      {status === "empty" && analysis && (
        <div className="bg-card border border-border rounded-xl p-6 space-y-3 text-center">
          <AlertTriangle size={22} className="mx-auto text-warning" />
          <p className="text-[15px] font-semibold text-foreground">No reliable prescription available</p>
          <p className="text-[13px] text-muted-foreground leading-relaxed max-w-xl mx-auto">{analysis.reason}</p>
          <div className="flex flex-wrap justify-center gap-2 pt-1">
            {(analysis.alternatives || []).map((a: string) => (
              <button key={a} onClick={() => {
                if (a === "Test Hypothesis") goHypothesis(null);
                else if (a === "Explore Data") (setPage as any)?.("data");
                else if (onAskQuestion) onAskQuestion(`Help me investigate ${analysis.metric || "my data"} further.`);
              }} className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-secondary border border-border text-foreground hover:border-primary/40 transition-colors">
                {a}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Idle */}
      {status === "idle" && (
        <div className="text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-sm font-medium text-foreground">Evaluate an intervention to begin</p>
          <p className="text-xs text-muted-foreground mt-1">Pick a target metric — ARIA finds the evidence-backed lever, or say there is none.</p>
        </div>
      )}

      {/* Results */}
      {status === "done" && analysis?.prescriptions && (
        <>
          {/* Decision summary (§31 top): compact, not KPI cards */}
          <div className="bg-card border border-border rounded-xl px-4 py-3 flex items-center gap-4 flex-wrap text-[12px]">
            <span><span className="font-bold text-foreground text-sm">{prescriptions.length}</span> <span className="text-muted-foreground">Recommended Actions</span></span>
            <span><span className="font-bold text-foreground text-sm">{analysis.signals?.supporting ?? 1}</span> <span className="text-muted-foreground">Supporting Signals</span></span>
            <span><span className="font-bold text-foreground text-sm">{prescriptions.length}</span> <span className="text-muted-foreground">Scenarios Available</span></span>
            <span className="ml-auto text-muted-foreground">Confidence: <span className="font-semibold text-foreground capitalize">{top?.confidence}</span></span>
          </div>

          <p className="text-[13px] text-foreground leading-relaxed bg-primary/5 border border-primary/20 rounded-xl px-4 py-3">{analysis.story}</p>

          {/* Plain-English summary: the whole decision in normal language */}
          {analysis.summary_plain && (
            <div className="bg-card border border-border rounded-xl px-4 py-3 space-y-1.5">
              <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Summary — in plain English</p>
              <p className="text-[13px] text-foreground leading-relaxed">{analysis.summary_plain}</p>
            </div>
          )}

          {/* Ranked shortlist (§22, inspo Action Engine cards) */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 items-start">
            {prescriptions.map((rx: any) => {
              const expanded = expandedId === rx.id;
              const isAccepted = accepted.includes(rx.id);
              return (
                <article key={rx.id} className={`bg-card border rounded-xl overflow-hidden transition-all ${expanded ? "border-primary/50 shadow-md lg:col-span-3" : "border-border hover:border-primary/30 hover:shadow-sm"}`}>
                  <div className="p-4 space-y-2.5">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase tracking-wide ${riskStyle[rx.risk] || riskStyle.medium}`}>{rx.risk} risk</span>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-secondary text-muted-foreground uppercase tracking-wide">{rx.confidence} confidence</span>
                      {rx.scenario_label === "recommended" && <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-primary text-primary-foreground uppercase tracking-wide">Recommended</span>}
                    </div>
                    <h3 className="text-sm font-semibold text-foreground leading-snug">{rx.title}</h3>
                    {rx.action_type === "qualitative" ? (
                      <p className="text-[11px] text-muted-foreground leading-relaxed line-clamp-2">{rx.summary}</p>
                    ) : (
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px]">
                      <span className="text-muted-foreground">Baseline <span className="text-foreground font-semibold">{fmtK(rx.impact?.baseline)}</span> <Tag tone="bg-secondary text-muted-foreground">Observed</Tag></span>
                      <span className="text-muted-foreground">Est. <span className={`font-semibold ${Number(rx.impact?.delta) >= 0 ? "text-positive" : "text-negative"}`}>{Number(rx.impact?.delta) >= 0 ? "+" : ""}{fmtK(rx.impact?.delta)} ({Number(rx.impact?.rel_pct) >= 0 ? "+" : ""}{rx.impact?.rel_pct}%)</span> <Tag tone="bg-primary/10 text-primary">Simulated</Tag></span>
                    </div>
                    )}
                    {rx.success_metric && (
                      <p className="text-[11px] text-muted-foreground leading-snug">
                        <span className="text-positive font-medium">Success looks like:</span> {rx.success_metric.direction}{rx.success_metric.target_pct != null ? ` (${rx.success_metric.target_pct > 0 ? "+" : ""}${rx.success_metric.target_pct}%)` : ""}{rx.review_period ? ` · review in ${rx.review_period}` : ""}
                      </p>
                    )}
                    <div className="text-[11px] text-muted-foreground leading-relaxed space-y-0.5">
                      {rx.action_type !== "qualitative" && rx.evidence?.driver && (
                      <p>· {rx.evidence?.driver?.replace(/_/g, " ")} ↔ {rx.evidence?.metric?.replace(/_/g, " ")}: r={rx.evidence?.effect_r}, n={Number(rx.evidence?.n).toLocaleString()}</p>
                      )}
                      <p>· {rx.summary}</p>
                    </div>
                    <ol className="text-[11px] text-foreground leading-relaxed space-y-0.5 bg-secondary/50 rounded-lg p-2.5">
                      <li>1. {rx.action_type === "investigate" ? `${rx.title}.` : `Apply: ${rx.title}.`}</li>
                      <li>2. {rx.recommended_next_analysis?.label}</li>
                    </ol>
                    <div className="flex items-center gap-1.5 flex-wrap pt-1">
                      <button onClick={() => setAccepted((a) => isAccepted ? a.filter((x) => x !== rx.id) : [...a, rx.id])}
                        className={`text-[11px] font-semibold px-2.5 py-1.5 rounded-lg transition-colors ${isAccepted ? "bg-positive/10 text-positive border border-positive/20" : "bg-primary text-primary-foreground hover:opacity-90"}`}>
                        {isAccepted ? "✓ Accepted" : "Accept"}
                      </button>
                      <button onClick={() => saveRx(rx)} className="text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">Save</button>
                      {onAskQuestion && <button onClick={() => onAskQuestion(`What data supports this: ${rx.title}?`)} className="text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors">Ask ARIA</button>}
                      <button onClick={() => { setExpandedId(expanded ? null : rx.id); if (!expanded) { setSimPct(Number(rx.impact?.driver_pct ?? -10)); setSimResult(null); } }}
                        className="ml-auto text-[11px] text-primary hover:underline inline-flex items-center gap-0.5">
                        {expanded ? <>Collapse <ChevronUp size={12} /></> : <>Evidence <ChevronDown size={12} /></>}
                      </button>
                    </div>
                  </div>

                  {expanded && (
                    <div className="border-t border-border px-4 py-4 space-y-4 bg-muted/20">
                      {/* WHY */}
                      <section>
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Why ARIA recommends this</p>
                        <p className="mt-1 text-[13px] text-foreground leading-relaxed">{rx.summary} {analysis.auto_note || ""}</p>
                      </section>
                      {/* EVIDENCE */}
                      <section className="border-t border-border pt-3">
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Evidence</p>
                        <div className="mt-2 rounded-lg border border-border bg-background/60 p-3">
                          <ChartFrame
                            title={rx.action_type === "investigate" ? `${rx.evidence?.metric?.replace(/_/g, " ")} by group` : `${analysis.evidence_viz?.x?.replace(/_/g, " ")} vs ${analysis.evidence_viz?.y?.replace(/_/g, " ")}`}
                            explanation="Hover any mark for its exact value."
                            empty={!((rx.action_type === "investigate" && rx.evidence?.groups?.length) || analysis.evidence_viz?.points?.length)}
                            height={200}
                          >
                          {rx.action_type === "investigate" && rx.evidence?.groups?.length ? (
                            <div className="space-y-2">
                              {(() => {
                                const max = Math.max(...rx.evidence.groups.map((g: any) => Number(g.mean)), 1);
                                return rx.evidence.groups.map((g: any) => (
                                  <div key={g.label} className="space-y-0.5">
                                    <div className="flex items-center justify-between text-[11px]">
                                      <span className="text-foreground font-medium">{g.label} <span className="text-muted-foreground">· n={g.n}</span></span>
                                      <span className="text-foreground font-semibold">{Number(g.mean).toLocaleString()}</span>
                                    </div>
                                    <div className="h-2 bg-secondary rounded-full overflow-hidden">
                                      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(3, (Number(g.mean) / max) * 100)}%` }} />
                                    </div>
                                  </div>
                                ));
                              })()}
                            </div>
                          ) : analysis.evidence_viz?.points?.length ? (
                            <ResponsiveContainer width="100%" height={220}>
                              <ScatterChart>
                                <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                                <XAxis dataKey="x" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} label={{ value: analysis.evidence_viz.x, position: "insideBottom", offset: -5, fontSize: 11, fill: axis }} />
                                <YAxis dataKey="y" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                                <Tooltip content={<BizTooltip metricNames={{ x: analysis.evidence_viz.x, y: analysis.evidence_viz.y }} />} />
                                <Scatter data={analysis.evidence_viz.points} fill="var(--primary)" fillOpacity={0.6} />
                                {trendLine && <Line type="linear" data={trendLine} dataKey="y" stroke="var(--primary)" strokeWidth={2} dot={false} />}
                              </ScatterChart>
                            </ResponsiveContainer>
                          ) : <p className="text-xs text-muted-foreground">Chart unavailable — values below still describe the evidence.</p>}
                          </ChartFrame>
                        </div>
                        {(rx.citations?.length > 0) && (
                          <div className="mt-2 space-y-1.5">
                            {rx.citations.map((c: any, i: number) => (
                              <div key={i} className="rounded-lg border border-border bg-secondary/40 px-3 py-2">
                                <p className="text-[11px] text-foreground leading-relaxed">“{c.quote}”</p>
                                <p className="text-[10px] text-muted-foreground mt-0.5">Source{c.page != null ? `: page ${c.page}` : ""} · quoted verbatim, not paraphrased</p>
                              </div>
                            ))}
                          </div>
                        )}
                        <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                          <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Effect (r)</p><p className="font-semibold text-foreground">{rx.evidence?.effect_r}</p></div>
                          <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Sample</p><p className="font-semibold text-foreground">{Number(rx.evidence?.n).toLocaleString()}</p></div>
                          <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">p-value</p><p className="font-semibold text-foreground">{rx.evidence?.p_value ?? analysis.fit?.p_value}</p></div>
                          <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Driver control</p><p className="font-semibold text-foreground capitalize">{analysis.control?.level?.replace(/_/g, " ")}</p></div>
                        </div>
                      </section>
                      {/* EXPECTED IMPACT */}
                      {rx.action_type === "qualitative" ? (
                      <section className="border-t border-border pt-3">
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Expected impact</p>
                        <p className="mt-1.5 text-[12px] text-foreground leading-relaxed">Not modeled — this lead comes from document passages, not measured numbers. Confirm it with data before expecting any effect.</p>
                      </section>
                      ) : (
                      <section className="border-t border-border pt-3">
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">{rx.action_type === "investigate" ? "Observed gap" : "Expected impact"}</p>
                        <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[12px]">
                          <div className="rounded-lg border border-border p-2.5"><p className="text-muted-foreground text-[10px] uppercase">Baseline <Tag tone="bg-secondary text-muted-foreground">{rx.impact?.labels?.baseline || "Observed"}</Tag></p><p className="font-bold text-foreground mt-0.5">{fmtK(rx.impact?.baseline)}</p></div>
                          <div className="rounded-lg border border-primary/30 bg-primary/5 p-2.5"><p className="text-muted-foreground text-[10px] uppercase">{rx.action_type === "investigate" ? "Top group" : "Scenario"} <Tag tone="bg-primary/10 text-primary">{rx.impact?.labels?.scenario || "Simulated"}</Tag></p><p className="font-bold text-foreground mt-0.5">{fmtK(rx.impact?.scenario)}</p></div>
                          <div className="rounded-lg border border-border p-2.5"><p className="text-muted-foreground text-[10px] uppercase">Change</p><p className={`font-bold mt-0.5 ${Number(rx.impact?.delta) >= 0 ? "text-positive" : "text-negative"}`}>{Number(rx.impact?.delta) >= 0 ? "+" : ""}{fmtK(rx.impact?.delta)} ({rx.impact?.rel_pct}%)</p></div>
                        </div>
                        <p className="mt-1.5 text-[11px] text-muted-foreground">{rx.action_type === "investigate" ? `Observed range across groups: ${fmtK(rx.impact?.range?.[0])} – ${fmtK(rx.impact?.range?.[1])}. A gap shows where to look, not what to change.` : `Estimated range: ${fmtK(rx.impact?.range?.[0])} – ${fmtK(rx.impact?.range?.[1])}. Simulated estimates are not guaranteed outcomes.`}</p>
                      </section>
                      )}
                      {/* SUCCESS LOOKS LIKE */}
                      {rx.success_metric && (
                      <section className="border-t border-border pt-3">
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Success looks like</p>
                        <p className="mt-1 text-[12px] text-foreground leading-relaxed">
                          {rx.success_metric.direction}{rx.success_metric.target_pct != null ? ` by about ${rx.success_metric.target_pct > 0 ? "+" : ""}${rx.success_metric.target_pct}%` : ""}{rx.success_metric.baseline != null ? ` (from ${fmtK(rx.success_metric.baseline)})` : ""}.
                          {rx.success_metric.note ? ` ${rx.success_metric.note}` : ""}{rx.review_period ? ` Review in ${rx.review_period}.` : ""}
                        </p>
                      </section>
                      )}
                      {/* SCENARIO COMPARISON (scenario actions only) */}
                      {rx.action_type === "scenario" && (
                      <section className="border-t border-border pt-3">
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Scenario comparison</p>
                        <div className="mt-2 grid grid-cols-3 gap-2 text-center text-[11px]">
                          {prescriptions.filter((p: any) => p.action_type === "scenario").map((p: any) => (
                            <button key={p.id} onClick={() => { setSimPct(Number(p.impact?.driver_pct)); setSimResult(null); }}
                              className={`rounded-lg border p-2.5 transition-colors ${p.id === rx.id ? "border-primary/50 bg-primary/5" : "border-border hover:border-primary/30"}`}>
                              <p className="text-muted-foreground uppercase text-[10px]">{p.scenario_label}</p>
                              <p className="font-bold text-foreground mt-0.5">{Number(p.impact?.driver_pct) > 0 ? "+" : ""}{p.impact?.driver_pct}% driver</p>
                              <p className={`font-semibold ${Number(p.impact?.delta) >= 0 ? "text-positive" : "text-negative"}`}>{Number(p.impact?.delta) >= 0 ? "+" : ""}{p.impact?.rel_pct}% KPI</p>
                            </button>
                          ))}
                        </div>
                        <div className="mt-3 rounded-lg border border-border p-3">
                          <p className="text-[11px] text-muted-foreground">Custom scenario: move {analysis.driver?.replace(/_/g, " ")} by <span className="font-bold text-foreground">{simPct > 0 ? "+" : ""}{simPct}%</span></p>
                          <div className="flex items-center gap-3 mt-1.5">
                            <input type="range" min={-30} max={30} step={5} value={simPct}
                              onChange={(e) => setSimPct(Number(e.target.value))}
                              className="flex-1 accent-[var(--primary)]" aria-label="Custom driver change percent" />
                            <button onClick={() => runScenario(rx, simPct)} disabled={simLoading}
                              className="text-[11px] font-semibold px-3 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50">
                              {simLoading ? "…" : "Model it"}
                            </button>
                          </div>
                          {simResult && !simResult.error && (
                            <p className="mt-2 text-[12px] text-foreground">Baseline <b>{fmtK(simResult.baseline)}</b> <Tag tone="bg-secondary text-muted-foreground">Observed</Tag> → Scenario <b>{fmtK(simResult.scenario)}</b> <Tag tone="bg-primary/10 text-primary">Simulated</Tag> (<span className={Number(simResult.delta) >= 0 ? "text-positive font-semibold" : "text-negative font-semibold"}>{Number(simResult.delta) >= 0 ? "+" : ""}{fmtK(simResult.delta)}</span>, range {fmtK(simResult.range?.[0])}–{fmtK(simResult.range?.[1])})</p>
                          )}
                          {simResult?.error && <p className="mt-2 text-[11px] text-warning">{simResult.error}</p>}
                        </div>
                      </section>
                      )}
                      {/* RISKS + SCORE */}
                      <section className="border-t border-border pt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Risks & limitations</p>
                          <ul className="mt-1 space-y-1">
                            {(rx.risk_reasons || []).concat(rx.limitations || []).slice(0, 5).map((l: string, i: number) => (
                              <li key={i} className="text-[11px] text-muted-foreground leading-relaxed">· {l}</li>
                            ))}
                          </ul>
                        </div>
                        <div>
                          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Why it ranks #{rx.rank} (score {rx.score})</p>
                          <div className="mt-1 space-y-1">
                            {Object.entries(rx.score_breakdown || {}).map(([k, v]: any) => (
                              <div key={k} className="flex items-center gap-2 text-[11px]">
                                <span className="text-muted-foreground w-32 truncate">{k.replace(/_/g, " ")}</span>
                                <div className="flex-1 h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full bg-primary rounded-full" style={{ width: `${Math.min(100, Number(v) * 4)}%` }} /></div>
                                <span className="text-foreground font-medium w-8 text-right">{v}</span>
                              </div>
                            ))}
                          </div>
                          {analysis.join && (
                            <p className="mt-1.5 text-[11px] text-muted-foreground">Driver from <span className="text-foreground font-medium">{analysis.driver_table}</span> via the declared join <span className="font-mono">{analysis.join}</span>.</p>
                          )}
                        </div>
                      </section>
                      {/* NEXT STEP */}
                      <section className="border-t border-border pt-3">
                        <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Next step</p>
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {rx.action_type !== "qualitative" && (
                          <button onClick={() => goHypothesis(rx)} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90"><FlaskConical size={12} /> Test Hypothesis</button>
                          )}
                          {rx.action_type === "scenario" && (
                          <button onClick={() => {
                            try { sessionStorage.setItem("aria_forecast_prefill", JSON.stringify({ metric: analysis.metric, driver: analysis.driver })); } catch {}
                            (setPage as any)?.("predictive");
                          }} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50"><TrendingUp size={12} /> Forecast Impact</button>
                          )}
                          {onAskQuestion && <button onClick={() => onAskQuestion(rx.action_type === "qualitative" ? `Dig into this passage further: ${rx.title}` : `Investigate ${analysis.driver} as a lever for ${analysis.metric}.`)} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50"><MessageSquare size={12} /> Ask ARIA</button>}
                        </div>
                      </section>
                    </div>
                  )}
                </article>
              );
            })}
          </div>

          {/* Saved */}
          <div className="bg-card border border-border rounded-xl p-4 space-y-2">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Saved prescriptions ({saved.length})</p>
            {saved.length === 0 && <p className="text-xs text-muted-foreground">Nothing saved yet — accepted actions you save will live here.</p>}
            {saved.map((s: any) => (
              <div key={s.id} className="flex items-center gap-2 text-xs border border-border rounded-lg px-3 py-2">
                <span className="text-foreground truncate flex-1">{s.title}</span>
                <span className="text-muted-foreground">{s.risk} risk</span>
                <button onClick={() => deleteSaved(s.id)} className="text-muted-foreground hover:text-negative">Remove</button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
