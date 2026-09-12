import { useState, useEffect, useCallback, useMemo } from "react";
import { Loader2, RefreshCw, AlertCircle, Sparkles, Target, TrendingUp, TrendingDown, Crosshair, Lightbulb, Check } from "lucide-react";
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { useTheme } from "../App";
import Evidence from "../components/Evidence";
import { ChartFrame, BizTooltip, useSeriesToggle, ToggleLegend } from "../components/charts";

interface PredictiveProps {
  insightResult?: any;
  goalResult?: any;
  connectionStatus?: string;
}

type PeriodTab = "Monthly" | "Quarterly" | "Yearly";

const plainName = (c: string) => (c || "").split(" (")[0].trim();

const fmtNum = (v: any) => {
  if (v === null || v === undefined || isNaN(Number(v))) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 1 });
};

const shortLabel = (label: string) => {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(String(label || ""));
  if (m) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return months[Number(m[2]) - 1] || label;
  }
  return String(label || "");
};

const monthKey = (label: string) => String(label || "").slice(0, 7);

function rebin(rows: any[], tab: PeriodTab) {
  if (tab === "Monthly") return rows;
  const groups = new Map<string, any>();
  for (const r of rows) {
    const mk = monthKey(r.label);
    if (!/^\d{4}-\d{2}$/.test(mk)) continue;
    const [y, m] = mk.split("-").map(Number);
    const key = tab === "Quarterly" ? `${y}-Q${Math.floor((m - 1) / 3) + 1}` : `${y}`;
    if (!groups.has(key)) groups.set(key, { label: key, short: key, actual: 0, forecast: 0, _a: false, _f: false });
    const g = groups.get(key);
    if (r.actual !== null && r.actual !== undefined) { g.actual += Number(r.actual) || 0; g._a = true; }
    if (r.forecast !== null && r.forecast !== undefined) { g.forecast += Number(r.forecast) || 0; g._f = true; }
  }
  return [...groups.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([, g]) => ({
      label: g.label,
      short: g.label,
      actual: g._a ? Math.round(g.actual * 100) / 100 : null,
      forecast: g._f ? Math.round(g.forecast * 100) / 100 : null,
    }));
}

const LOAD_STAGES = [
  "Analyzing time-series data…",
  "Preparing historical observations…",
  "Building forecast…",
  "Calculating uncertainty…",
  "Generating explanation…",
];

export default function Predictive({ insightResult = null, goalResult = null, connectionStatus = "not-connected" }: PredictiveProps) {
  const { isDark } = useTheme();
  const [forecast, setForecast] = useState<any>(null);
  const [forecastInfo, setForecastInfo] = useState<any>(null);
  const [selection, setSelection] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [loadStage, setLoadStage] = useState(0);
  const [error, setError] = useState("");
  const [elig, setElig] = useState<any>(null);
  const [eligLoading, setEligLoading] = useState(false);
  const [eligError, setEligError] = useState("");
  const [selectedTarget, setSelectedTarget] = useState<string>("");
  const [selectedTable, setSelectedTable] = useState<string>("");
  const [selectedTime, setSelectedTime] = useState<string>("");
  const [horizon, setHorizon] = useState(6);
  const [tab, setTab] = useState<PeriodTab>("Monthly");
  const [scenarioPct, setScenarioPct] = useState(10);
  const [scenario, setScenario] = useState<any>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioError, setScenarioError] = useState("");
  const fcToggle = useSeriesToggle(["Actual", "Forecast", "Average", "Likely range"]);

  const authHeader = () => {
    const token = localStorage.getItem("aria_auth_token");
    return { Authorization: `Bearer ${token}` };
  };

  // ---- Eligibility: what can actually be forecast ----
  const loadEligibility = useCallback(async () => {
    setEligLoading(true);
    setEligError("");
    try {
      const res = await fetch("/api/predictive/eligibility", { headers: authHeader() });
      const data = await res.json();
      if (data.ok) {
        setElig(data);
        const rec = data.recommended;
        if (rec) {
          setSelectedTarget((prev) => prev || rec.measure);
          setSelectedTable((prev) => prev || rec.table);
          setSelectedTime((prev) => prev || rec.time_dim);
        }
      } else {
        setEligError(data.detail || "Couldn't inspect the data for forecasting.");
      }
    } catch (e: any) {
      setEligError(e?.message || "Couldn't inspect the data for forecasting.");
    } finally {
      setEligLoading(false);
    }
  }, []);

  useEffect(() => {
    if (connectionStatus === "connected") loadEligibility();
    else { setElig(null); setForecast(null); setError(""); }
  }, [connectionStatus, loadEligibility]);

  const tables: any[] = elig?.tables || [];
  const activeTable = tables.find((t) => t.table === selectedTable) || tables.find((t) => (t.measures || []).includes(selectedTarget)) || null;
  const activeMeasures: string[] = activeTable?.measures || [];
  const activeTimes: any[] = activeTable?.time_dims || [];
  const historyPoints = activeTable && selectedTime
    ? (activeTimes.find((d) => d.column === selectedTime)?.distinct ?? null)
    : (elig?.recommended?.history_points ?? null);

  const runScenario = useCallback(async () => {
    setScenarioLoading(true);
    setScenarioError("");
    try {
      const res = await fetch("/api/predictive/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({
          column: plainName(selectedTarget) || undefined,
          pct_change: Number(scenarioPct) || 0,
          periods: 3,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setScenario(data);
      } else {
        setScenario(null);
        setScenarioError(data.detail || "Couldn't run that scenario. Try a different number.");
      }
    } catch (e: any) {
      setScenario(null);
      setScenarioError(e?.message || "Couldn't run that scenario.");
    } finally {
      setScenarioLoading(false);
    }
  }, [selectedTarget, scenarioPct]);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";
  const actualColor = "#14B8A6";
  const projectionColor = "#6366F1";
  const avgColor = "#64748B";

  const insightPredictions = insightResult?.predictions || {};
  const hasInsightPredictions = insightPredictions && (insightPredictions.valid || insightPredictions.points?.length > 0);

  const fetchForecast = useCallback(async (target?: string, timeDim?: string, h?: number) => {
    const t = plainName(target || selectedTarget || "");
    const td = plainName(timeDim || selectedTime || "");
    const hr = h !== undefined ? h : horizon;
    if (!t) return;

    setLoading(true);
    setLoadStage(0);
    setError("");
    const stageTimer = setInterval(() => setLoadStage((s) => Math.min(s + 1, LOAD_STAGES.length - 1)), 2500);
    try {
      const res = await fetch("/api/predictive/forecast", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({
          question: td ? `Forecast ${t} by ${td} over time` : `Forecast ${t} over time`,
          column: t,
          time_dim: td || undefined,
          horizon: hr,
        }),
      });
      const data = await res.json();
      if (data.ok && data.forecast) {
        setForecast(data.forecast);
        setForecastInfo(data.info || null);
        setSelection(data.selection || null);
        const f = data.forecast;
        if (!f.valid && !(f.points?.length > 0)) {
          if ((data.info?.rows_analyzed ?? 1) === 0) {
            setError("There's no data to forecast yet. Connect a source with numbers tracked over time, then try again.");
          } else {
            setError(f.reason || "Couldn't build a reliable forecast from this data. Try a different number above.");
          }
        }
      } else {
        setError(data.detail || "Couldn't build a forecast. Try a different number above.");
        setForecast(null);
      }
    } catch (e: any) {
      setError(e.message || "Couldn't build a forecast. Check your connection and try again.");
      setForecast(null);
    } finally {
      clearInterval(stageTimer);
      setLoading(false);
    }
  }, [selectedTarget, selectedTime, horizon]);

  // Auto-run once eligibility + a valid default exist.
  useEffect(() => {
    if (connectionStatus !== "connected" || !elig?.eligible || !selectedTarget) return;
    if (!hasInsightPredictions && (!forecast || forecast.points?.length === 0)) {
      const timer = setTimeout(() => fetchForecast(), 500);
      return () => clearTimeout(timer);
    }
  }, [connectionStatus, elig, selectedTarget, hasInsightPredictions, fetchForecast]);

  const useAutomatic = () => {
    const rec = elig?.recommended;
    if (!rec) return;
    setSelectedTable(rec.table);
    setSelectedTarget(rec.measure);
    setSelectedTime(rec.time_dim);
    setForecast(null);
    setError("");
    setTimeout(() => fetchForecast(rec.measure, rec.time_dim), 50);
  };

  const predictions = forecast || insightPredictions;
  const hasPredictions = predictions && (predictions.valid || predictions.points?.length > 0);
  const targetName = plainName(selection?.measure || predictions?.column || selectedTarget);
  const timeName = plainName(selection?.time_dim || selectedTime);
  const accuracy = predictions?.accuracy_pct ?? null;

  const chartRows = useMemo(() => {
    const hist = Array.isArray(predictions?.history) ? predictions.history : [];
    const pts: any[] = Array.isArray(predictions?.points) ? predictions.points : [];
    const rows: any[] = [
      ...hist.map((h: any) => ({ label: h.label, short: shortLabel(h.label), actual: h.actual, forecast: null, lower95: null, upper95: null })),
      ...pts.map((p: any) => ({
        label: p.label,
        short: shortLabel(p.label),
        actual: null,
        forecast: p.forecast ?? p.value ?? null,
        lower95: p.lower95 ?? null,
        upper95: p.upper95 ?? null,
      })),
    ];
    const rebinned = rebin(rows, tab);
    return rebinned.map((r: any) => ({ ...r, short: r.short || shortLabel(r.label) }));
  }, [predictions, tab]);

  const historyVals: number[] = useMemo(() => {
    const hist = Array.isArray(predictions?.history) ? predictions.history : [];
    return hist.map((h: any) => Number(h.actual)).filter((v: number) => !isNaN(v));
  }, [predictions]);

  const lastActual = predictions?.last_actual?.value ?? (historyVals.length ? historyVals[historyVals.length - 1] : null);
  const fwdPts: any[] = Array.isArray(predictions?.points) ? predictions.points : [];
  const fwdVals = fwdPts.map((p: any) => Number(p.forecast ?? p.value)).filter((v: number) => !isNaN(v));
  const projectedTotal = fwdVals.reduce((a, b) => a + b, 0);
  const avgActual = historyVals.length ? historyVals.reduce((a, b) => a + b, 0) / historyVals.length : null;
  const pctChange = predictions?.projected_pct_change ?? null;
  const historyCount = forecastInfo?.rows_analyzed ?? historyVals.length;

  const sumKey = (k: string) => fwdPts.reduce((a, p) => a + (Number(p[k]) || 0), 0);
  const scenarios = useMemo(() => {
    if (!fwdPts.length || lastActual === null) return null;
    const base = (avgActual !== null ? avgActual * Math.max(1, fwdVals.length) : Math.abs(Number(lastActual)) * Math.max(1, fwdVals.length)) || 1;
    const mk = (label: string, total: number, tone: string, note: string, sub: string) => {
      const pct = ((total - base) / Math.abs(base)) * 100;
      return { label, total, tone, note, sub, pct, ofTarget: base ? (total / base) * 100 : 100 };
    };
    return [
      mk("Best Case", sumKey("upper95") || projectedTotal, "good", "Upper edge of the expected range", "If momentum holds"),
      mk("Commit", projectedTotal, "base", "Central projection", "Based on recent trend"),
      mk("Worst Case", sumKey("lower95") || projectedTotal, "bad", "Lower edge of the expected range", "If momentum slows"),
    ];
  }, [fwdPts, lastActual, avgActual, projectedTotal, fwdVals.length]);
  const scenMax = scenarios ? Math.max(...scenarios.map((s) => s.total), 1) : 1;

  const recentTop = useMemo(() => {
    const hist = Array.isArray(predictions?.history) ? predictions.history : [];
    const total = historyVals.reduce((a, b) => a + b, 0);
    return [...hist]
      .sort((a: any, b: any) => Number(b.actual) - Number(a.actual))
      .slice(0, 3)
      .map((h: any) => ({ label: shortLabel(h.label), value: Number(h.actual), share: total ? (Number(h.actual) / total) * 100 : 0 }));
  }, [predictions, historyVals]);

  const momDelta = historyVals.length >= 2 && historyVals[historyVals.length - 2]
    ? ((historyVals[historyVals.length - 1] - historyVals[historyVals.length - 2]) / Math.abs(historyVals[historyVals.length - 2])) * 100
    : null;

  // Dynamic insights — only from calculated numbers, never invented.
  const insights: string[] = useMemo(() => {
    const out: string[] = [];
    if (!hasPredictions || !targetName) return out;
    if (pctChange !== null && pctChange > 1) out.push(`${targetName} is expected to keep rising over the next ${fwdVals.length} ${fwdVals.length === 1 ? "period" : "periods"} (about +${pctChange.toFixed(1)}%).`);
    else if (pctChange !== null && pctChange < -1) out.push(`${targetName} is expected to decline over the next ${fwdVals.length} ${fwdVals.length === 1 ? "period" : "periods"} (about ${pctChange.toFixed(1)}%).`);
    else if (pctChange !== null) out.push(`${targetName} is expected to hold roughly steady.`);
    if (fwdPts.length >= 2) {
      const w0 = Math.abs(Number(fwdPts[0].upper95 ?? 0) - Number(fwdPts[0].lower95 ?? 0));
      const w1 = Math.abs(Number(fwdPts[fwdPts.length - 1].upper95 ?? 0) - Number(fwdPts[fwdPts.length - 1].lower95 ?? 0));
      if (w1 > w0 * 1.2) out.push("Forecast uncertainty widens toward the end of the horizon — near-term points are the most trustworthy.");
    }
    if (avgActual !== null && historyVals.length >= 2) {
      const recent = historyVals.slice(-3).reduce((a, b) => a + b, 0) / Math.min(3, historyVals.length);
      if (recent > avgActual * 1.1) out.push("Recent values are running above the historical average, which lifts the projection.");
      else if (recent < avgActual * 0.9) out.push("Recent values are running below the historical average, which drags the projection down.");
    }
    return out.slice(0, 3);
  }, [hasPredictions, targetName, pctChange, fwdVals, fwdPts, avgActual, historyVals]);

  const horizonWarning = historyPoints !== null && horizon > historyPoints
    ? `Heads up: ${horizon} periods ahead from only ${historyPoints} past points — treat the far end as directional.`
    : null;

  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-20">
          <div className="w-16 h-16 rounded-2xl mx-auto mb-5 flex items-center justify-center bg-primary">
            <TrendingUp size={24} className="text-primary-foreground" />
          </div>
          <h2 className="text-2xl font-semibold text-foreground tracking-tight mb-2">Forecast</h2>
          <p className="text-sm text-muted-foreground mb-4 max-w-sm mx-auto">
            Connect your data and ARIA will project your key numbers into the future.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-foreground tracking-tight">Forecast</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Project your key numbers into the future.</p>
        </div>
        <div className="flex bg-card border border-border rounded-lg p-0.5 text-xs font-medium">
          {(["Monthly", "Quarterly", "Yearly"] as PeriodTab[]).map((p) => (
            <button
              key={p}
              onClick={() => setTab(p)}
              className={`px-3 py-1.5 rounded-md transition-colors ${tab === p ? "bg-secondary text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            >
              {p}
            </button>
          ))}
        </div>
      </div>

      {/* Eligibility / setup */}
      {eligLoading && (
        <div className="bg-card border border-border rounded-xl p-5 flex items-center gap-3">
          <Loader2 size={18} className="animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Inspecting your data for forecastable numbers and time…</p>
        </div>
      )}
      {eligError && !eligLoading && (
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-4">
          <p className="text-sm text-negative font-medium">{eligError}</p>
          <button onClick={loadEligibility} className="text-xs text-primary hover:underline mt-1">Retry inspection</button>
        </div>
      )}

      {elig && !elig.eligible && !eligLoading && (
        <div className="bg-card border border-border rounded-xl p-5 space-y-2">
          <p className="text-sm font-semibold text-foreground">Forecasting isn't available for this dataset yet.</p>
          {(elig.reasons || []).map((r: string, i: number) => (
            <p key={i} className="text-sm text-muted-foreground leading-relaxed">· {r}</p>
          ))}
          <p className="text-xs text-muted-foreground pt-1">ARIA needs a time dimension and a measurable number with enough history. Try connecting a dataset with dates and amounts.</p>
        </div>
      )}

      {elig?.eligible && (
        <div className="bg-card border border-border rounded-xl p-4">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-3">Forecast setup</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Target</p>
              <select
                value={selectedTarget}
                onChange={(e) => {
                  const v = e.target.value;
                  setSelectedTarget(v);
                  const owner = tables.find((t) => (t.measures || []).includes(v));
                  if (owner) {
                    setSelectedTable(owner.table);
                    const td = (owner.time_dims || [])[0]?.column || "";
                    setSelectedTime(td);
                  }
                  setForecast(null); setError("");
                }}
                className="w-full bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none cursor-pointer"
              >
                {tables.filter((t) => (t.measures || []).length).map((t) => (
                  <optgroup key={t.table} label={t.table}>
                    {t.measures.map((m: string) => (
                      <option key={`${t.table}.${m}`} value={m}>{m}</option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Time dimension</p>
              <select
                value={selectedTime}
                onChange={(e) => { setSelectedTime(e.target.value); setForecast(null); setError(""); }}
                className="w-full bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none cursor-pointer"
              >
                {activeTimes.length === 0 && <option value="">Auto-detect…</option>}
                {activeTimes.map((d: any) => (
                  <option key={d.column} value={d.column}>{d.column}{d.kind === "text" ? " (text)" : ""}</option>
                ))}
              </select>
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Forecast</p>
              <select
                value={horizon}
                onChange={(e) => setHorizon(Number(e.target.value))}
                className="w-full bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none cursor-pointer"
              >
                {[3, 6, 12].map((h) => (
                  <option key={h} value={h}>{h} periods</option>
                ))}
              </select>
            </div>
            <button
              onClick={() => fetchForecast()}
              disabled={loading || !selectedTarget}
              className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {loading ? "Working…" : hasPredictions ? "Update" : "Build forecast"}
            </button>
          </div>
          {timeName && <p className="text-[11px] text-muted-foreground mt-2">Time base: {timeName} · detected from your data, changeable above.</p>}
          {horizonWarning && <p className="text-[11px] text-warning mt-1">{horizonWarning}</p>}
        </div>
      )}

      {loading && (
        <div className="bg-card border border-border rounded-xl p-6 flex flex-col items-center gap-3">
          <Loader2 size={22} className="animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">{LOAD_STAGES[loadStage]}</p>
        </div>
      )}

      {error && !hasPredictions && !loading && (
        <div className="bg-card border border-warning/40 rounded-xl p-4 space-y-2">
          <p className="text-sm font-semibold text-foreground">Couldn't forecast that selection</p>
          <p className="text-sm text-muted-foreground leading-relaxed">{error}</p>
          <button onClick={useAutomatic} className="text-xs font-semibold text-primary hover:underline">Try automatic selection</button>
        </div>
      )}

      {!hasPredictions && !loading && !error && elig?.eligible && (
        <div className="text-center py-10 bg-card border border-border rounded-xl">
          <TrendingUp size={28} className="text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Your forecast will appear here.</p>
        </div>
      )}

      {hasPredictions && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <div className="lg:col-span-2 space-y-4">
            <div className="bg-card border border-border rounded-xl p-5">
              <ChartFrame
                title={`${plainName(selectedTarget) || "Metric"} forecast`}
                explanation="Solid line: what actually happened. Dashed line: what the model expects next. Click legend items to toggle series."
                empty={chartRows.length === 0}
                emptyText="Chart couldn't be drawn from this result — the numbers above still apply."
                height={300}
              >
              <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
                <ToggleLegend
                  items={["Actual", "Forecast", ...(avgActual !== null ? ["Average"] : []), ...(tab === "Monthly" ? ["Likely range"] : [])]}
                  isHidden={fcToggle.isHidden}
                  onToggle={fcToggle.toggle}
                  colors={{ Actual: actualColor, Forecast: projectionColor, Average: avgColor, "Likely range": projectionColor }}
                />
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-bold px-2.5 py-1 rounded-full bg-secondary text-foreground">
                    {fmtNum(projectedTotal)} total
                  </span>
                  <button
                    onClick={() => fetchForecast()}
                    disabled={loading}
                    className="flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-lg bg-secondary hover:bg-secondary/70 text-foreground transition-colors border border-border disabled:opacity-50"
                  >
                    <RefreshCw size={11} className={loading ? "animate-spin" : ""} /> Refresh
                  </button>
                </div>
              </div>
              {chartRows.length > 0 ? (
                <ResponsiveContainer width="100%" height={248}>
                  <ComposedChart data={chartRows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey="short" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} minTickGap={20} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={56} tickFormatter={(v: number) => fmtNum(v)} />
                    <Tooltip
                      content={<BizTooltip metricNames={{ actual: "Actual", forecast: "Forecast", upper95: "Likely high", lower95: "Likely low" }} />}
                    />
                    {tab === "Monthly" && !fcToggle.isHidden("Likely range") && (
                      <Area type="monotone" dataKey="upper95" stroke="none" fill={projectionColor} fillOpacity={0.14} connectNulls name="Likely range" />
                    )}
                    {tab === "Monthly" && !fcToggle.isHidden("Likely range") && (
                      <Area type="monotone" dataKey="lower95" stroke="none" fill="var(--card)" fillOpacity={1} connectNulls name="Likely range" />
                    )}
                    {avgActual !== null && !fcToggle.isHidden("Average") && (
                      <ReferenceLine y={avgActual} stroke={avgColor} strokeWidth={1.5} strokeDasharray="4 4" />
                    )}
                    {!fcToggle.isHidden("Actual") && (
                      <Line type="monotone" dataKey="actual" stroke={actualColor} strokeWidth={2} dot={{ r: 2 }} connectNulls name="Actual" />
                    )}
                    {!fcToggle.isHidden("Forecast") && (
                      <Line type="monotone" dataKey="forecast" stroke={projectionColor} strokeWidth={2} strokeDasharray="6 4" dot={{ r: 3 }} connectNulls name="Forecast" />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-muted-foreground py-8 text-center">Chart couldn't be drawn from this result — the numbers above still apply.</p>
              )}
              </ChartFrame>
            </div>

            {scenarios && (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {scenarios.map((s) => (
                  <div key={s.label} className="bg-card border border-border rounded-xl p-4 space-y-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="w-7 h-7 rounded-full flex items-center justify-center"
                        style={{
                          background: s.tone === "good" ? "rgba(5,150,105,0.12)" : s.tone === "bad" ? "rgba(239,68,68,0.12)" : "rgba(99,102,241,0.12)",
                          color: s.tone === "good" ? "#059669" : s.tone === "bad" ? "#EF4444" : "#6366F1",
                        }}
                      >
                        {s.tone === "good" ? <TrendingUp size={14} /> : s.tone === "bad" ? <TrendingDown size={14} /> : <Crosshair size={14} />}
                      </span>
                      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">{s.label}</p>
                      <span className={`ml-auto text-[11px] font-bold ${s.pct >= 0 ? "text-positive" : "text-negative"}`}>
                        {s.pct >= 0 ? "+" : ""}{s.pct.toFixed(0)}%
                      </span>
                    </div>
                    <p className="text-xl font-bold text-foreground leading-none">{fmtNum(s.total)}</p>
                    <p className="text-[11px] text-muted-foreground">{s.ofTarget.toFixed(0)}% of average pace</p>
                    <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: `${scenMax ? Math.max(4, (s.total / scenMax) * 100) : 4}%`,
                          background: s.tone === "good" ? "#059669" : s.tone === "bad" ? "#EF4444" : "#6366F1",
                        }}
                      />
                    </div>
                    <div className="space-y-0.5 pt-0.5">
                      {[s.note, s.tone === "base" ? "Based on recent trend" : s.tone === "good" ? "If momentum holds" : "If momentum slows"].map((b) => (
                        <p key={b} className="text-[11px] text-muted-foreground flex items-center gap-1.5">
                          <Check size={11} className="text-positive flex-shrink-0" /> {b}
                        </p>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {insights.length > 0 && (
              <div className="bg-card border border-border rounded-xl p-4 space-y-1.5">
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">What this means</p>
                {insights.map((ins, i) => (
                  <p key={i} className="text-sm text-foreground leading-relaxed">· {ins}</p>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-4">
            <div className="bg-primary/5 border border-primary/20 rounded-xl p-4 space-y-1.5">
              <div className="flex items-center gap-2">
                <Sparkles size={13} className="text-primary" />
                <p className="text-[11px] font-semibold text-primary uppercase tracking-wider">Summary</p>
              </div>
              <p className="text-sm text-foreground leading-relaxed">
                {targetName ? <><strong>{targetName}</strong> is </> : "Your number is "}
                {pctChange !== null && pctChange > 1 && <>heading up about <strong>+{pctChange.toFixed(1)}%</strong></>}
                {pctChange !== null && pctChange < -1 && <>heading down about <strong>{pctChange.toFixed(1)}%</strong></>}
                {(pctChange === null || Math.abs(pctChange) <= 1) && <>holding roughly steady</>}
                {historyCount > 0 && <> across {historyCount} past {historyCount === 1 ? "point" : "points"}</>}.
              </p>
            </div>

            <div className="bg-card border border-border rounded-xl p-4 space-y-3">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Key factors</p>
              {[
                { icon: Target, label: "Period average", value: avgActual !== null ? fmtNum(avgActual) : "—", pill: momDelta !== null ? `${momDelta > 0 ? "+" : ""}${momDelta.toFixed(1)}%` : null, good: (momDelta ?? 0) >= 0 },
                { icon: TrendingUp, label: "Last actual", value: lastActual !== null ? fmtNum(lastActual) : "—", pill: null as string | null, good: true },
                { icon: Crosshair, label: "Past accuracy", value: accuracy !== null ? `${accuracy.toFixed(0)}%` : "—", pill: accuracy !== null ? (accuracy >= 70 ? "Reliable" : "Weak") : null, good: (accuracy ?? 0) >= 70 },
                { icon: Sparkles, label: "History", value: historyCount > 0 ? `${historyCount} periods` : "—", pill: null as string | null, good: true },
              ].map((f) => (
                <div key={f.label} className="flex items-center gap-2.5">
                  <span className="w-7 h-7 rounded-full bg-primary/10 text-primary flex items-center justify-center flex-shrink-0">
                    <f.icon size={13} />
                  </span>
                  <span className="text-[13px] text-muted-foreground">{f.label}</span>
                  <span className="ml-auto text-[13px] font-bold text-foreground">{f.value}</span>
                  {f.pill && (
                    <span
                      className="text-[10px] font-bold px-1.5 py-0.5 rounded"
                      style={f.good ? { background: "rgba(5,150,105,0.12)", color: "#059669" } : { background: "rgba(239,68,68,0.12)", color: "#EF4444" }}
                    >
                      {f.pill}
                    </span>
                  )}
                </div>
              ))}
            </div>

            {recentTop.length > 0 && (
              <div className="bg-card border border-border rounded-xl p-4 space-y-2.5">
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Largest periods</p>
                {recentTop.map((r) => (
                  <div key={r.label} className="space-y-1">
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-foreground font-medium">{r.label}</span>
                      <span className="text-muted-foreground">{fmtNum(r.value)} · {r.share.toFixed(0)}%</span>
                    </div>
                    <div className="h-1.5 bg-secondary rounded-full overflow-hidden">
                      <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, r.share)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="rounded-xl p-3.5 flex items-start gap-2.5 bg-secondary/60 border border-border">
              <Lightbulb size={14} className="text-primary flex-shrink-0 mt-0.5" />
              <p className="text-xs text-foreground leading-relaxed">
                <strong>Tip:</strong>{" "}
                {accuracy !== null && accuracy < 70
                  ? "Accuracy is below 70% — treat this as directional and watch incoming actuals."
                  : pctChange !== null && pctChange > 10
                    ? "Strong upward momentum — make sure capacity can cover the projected peak."
                    : pctChange !== null && pctChange < -10
                      ? "A downward trend is ahead — consider actions to recover volume."
                      : "The projection tracks your recent average — small moves compound over time."}
              </p>
            </div>

            {/* Evidence (s.txt): method, inputs, confidence — closed by default */}
            <Evidence
              sections={[
                { title: "Data analyzed", body: `${targetName || "The selected number"} over the last ${historyCount > 0 ? `${historyCount} periods` : "available history"}.` },
                { title: "Key observation", body: pctChange !== null && Math.abs(pctChange) > 1 ? `Recent momentum points ${pctChange > 0 ? "up" : "down"} about ${Math.abs(Math.round(pctChange))}%.` : "Recent values sit close to their average — no strong direction." },
                { title: "Analysis method", body: `Trend-based forecasting model${forecast?.method ? ` (${forecast.method})` : ""}, validated against past actuals before showing any projection.` },
                { title: "Confidence", body: accuracy !== null ? `${accuracy >= 70 ? "Reliable" : "Weak"} in backtesting (${Math.round(accuracy)}% accuracy). Uncertainty grows further out — treat distant points as directional.` : "Backtesting could not score this series — treat the projection as directional." },
                { title: "Assumptions", body: "Past patterns continue; no shocks, price changes, or seasonality shifts are modeled. A forecast is an estimate, not a promise." },
              ]}
            />
          </div>
        </div>
      )}

      {hasPredictions && (
        <div className="bg-card border border-border rounded-xl p-4 space-y-3">
          <div>
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">What-if estimate</p>
            <p className="text-xs text-muted-foreground mt-0.5">Slide to see what happens if {targetName || "your number"} changes. An estimate, not a forecast.</p>
          </div>
          <div className="flex flex-wrap items-center gap-4">
            <input
              type="range" min={-95} max={95} step={5} value={scenarioPct}
              onChange={(e) => setScenarioPct(Number(e.target.value))}
              className="flex-1 min-w-[160px] accent-[var(--primary)]"
              aria-label="Percentage change"
            />
            <span className={`text-lg font-bold w-20 text-right ${scenarioPct >= 0 ? "text-positive" : "text-negative"}`}>
              {scenarioPct >= 0 ? "+" : ""}{scenarioPct}%
            </span>
            <button
              onClick={() => runScenario()}
              disabled={scenarioLoading}
              className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {scenarioLoading ? "Calculating..." : "See result"}
            </button>
          </div>
          {scenarioError && <p className="text-sm text-negative font-medium">{scenarioError}</p>}
          {scenario && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="border border-border rounded-xl p-4 space-y-1">
                <p className="text-xs text-muted-foreground">Recent average</p>
                <p className="text-xl font-bold text-foreground">{Number(scenario.baseline).toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">{scenario.periods_used} recent {scenario.periods_used === 1 ? "period" : "periods"}</p>
              </div>
              <div className="border border-primary/40 bg-primary/5 rounded-xl p-4 space-y-1">
                <p className="text-xs text-muted-foreground">With {scenario.pct_change > 0 ? "+" : ""}{scenario.pct_change}%</p>
                <p className="text-xl font-bold text-foreground">{Number(scenario.scenario_value).toLocaleString()}</p>
                <p className={`text-xs font-semibold ${scenario.delta >= 0 ? "text-positive" : "text-negative"}`}>
                  {scenario.delta >= 0 ? "+" : ""}{Number(scenario.delta).toLocaleString()} vs recent average
                </p>
              </div>
              <div className="border border-border rounded-xl p-4 space-y-1">
                <p className="text-xs text-muted-foreground">Keep in mind</p>
                <p className="text-xs text-foreground leading-relaxed">Uniform change on recent months — sensitivity analysis, not a forecast.</p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
