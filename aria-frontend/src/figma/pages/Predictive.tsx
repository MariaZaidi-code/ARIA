import { useState, useEffect, useCallback } from "react";
import { TrendingUp, Loader2, RefreshCw, AlertCircle, ChevronDown, SlidersHorizontal } from "lucide-react";
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { useTheme } from "../App";

interface PredictiveProps {
  insightResult?: any;
  goalResult?: any;
  connectionStatus?: string;
}

export default function Predictive({ insightResult = null, goalResult = null, connectionStatus = "not-connected" }: PredictiveProps) {
  const { isDark } = useTheme();
  const [forecast, setForecast] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [dateColumns, setDateColumns] = useState<string[]>([]);
  const [selectedTarget, setSelectedTarget] = useState<string>("");
  const [selectedTime, setSelectedTime] = useState<string>("");
  const [horizon, setHorizon] = useState(6);
  const [showControls, setShowControls] = useState(false);
  // What-if scenario (spec §16): deterministic estimate, never a forecast.
  const [scenarioPct, setScenarioPct] = useState(10);
  const [scenario, setScenario] = useState<any>(null);
  const [scenarioLoading, setScenarioLoading] = useState(false);
  const [scenarioError, setScenarioError] = useState("");

  const runScenario = useCallback(async () => {
    setScenarioLoading(true);
    setScenarioError("");
    try {
      if (connectionStatus !== "connected") {
        setScenario(null);
        setScenarioError("Connect a data source to run a scenario.");
        return;
      }
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/predictive/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({
          column: (selectedTarget || "").split(" (")[0] || undefined,
          pct_change: Number(scenarioPct) || 0,
          periods: 3,
        }),
      });
      const data = await res.json();
      if (data.ok) {
        setScenario(data);
      } else {
        setScenario(null);
        setScenarioError(data.detail || "Scenario analysis failed.");
      }
    } catch (e: any) {
      setScenario(null);
      setScenarioError(e?.message || "Scenario analysis failed.");
    } finally {
      setScenarioLoading(false);
    }
  }, [selectedTarget, scenarioPct, connectionStatus]);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  // Try predictions from insightResult first
  const insightPredictions = insightResult?.predictions || {};
  const hasInsightPredictions = insightPredictions && (insightPredictions.valid || insightPredictions.points?.length > 0);

  // Load available columns from schema/session when connected
  const loadSchemaInfo = useCallback(async () => {
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/session/status", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.db_name || data.connection_status === "connected") {
        // Try to get schema info for column suggestions
        try {
          const schemaRes = await fetch("/api/schema", {
            headers: { Authorization: `Bearer ${token}` },
          });
          const schemaData = await schemaRes.json();
          if (schemaData.ok && schemaData.schema && schemaData.schema.tables) {
            const tables = schemaData.schema.tables;
            const allNumeric: string[] = [];
            const allDates: string[] = [];
            for (const [tname, tinfo] of Object.entries(tables as Record<string, any>)) {
              const cols = tinfo.columns || [];
              for (const c of cols) {
                const cname = typeof c === "string" ? c : c.column || c.name || "";
                const ctype = typeof c === "string" ? "" : c.data_type || c.type || "";
                if (cname) {
                  const lowType = String(ctype).toLowerCase();
                  if (lowType.includes("date") || lowType.includes("time") || lowType.includes("timestamp")) {
                    allDates.push(`${cname} (${tname})`);
                  } else if (lowType.includes("numeric") || lowType.includes("int") || lowType.includes("float") || lowType.includes("decimal") || lowType.includes("real") || lowType.includes("double")) {
                    allNumeric.push(`${cname} (${tname})`);
                  }
                }
              }
            }
            setDateColumns(allDates.slice(0, 8));
            setColumns(allNumeric.slice(0, 8));
            // Prefer real measures over id/key/code columns (forecasting a
            // synthetic key is meaningless; the backend refuses it too).
            const isIdLike = (c: string) => {
              const base = c.split(" (")[0].toLowerCase().trim();
              return base.endsWith("_id") || base.endsWith("_key") || ["id", "key", "code"].includes(base);
            };
            const measures = allNumeric.filter((c) => !isIdLike(c));
            if (allNumeric.length > 0 && !selectedTarget) {
              setSelectedTarget(measures.length > 0 ? measures[0] : allNumeric[0]);
            }
            if (allDates.length > 0 && !selectedTime) {
              setSelectedTime(allDates[0]);
            }
          }
        } catch {
          // Schema fetch optional
        }
      }
    } catch {
      // Session fetch optional
    }
  }, [selectedTarget, selectedTime]);

  useEffect(() => {
    loadSchemaInfo();
  }, [loadSchemaInfo]);

  const fetchForecast = useCallback(async (target?: string, timeDim?: string, h?: number) => {
    const t = target || selectedTarget || columns[0] || "main measure";
    const d = timeDim || selectedTime || dateColumns[0] || "date";
    const hr = h !== undefined ? h : horizon;

    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/predictive/forecast", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          question: `Forecast ${t.split(" (")[0]} over ${d.split(" (")[0] || "time"}`,
          column: t.split(" (")[0],
          horizon: hr,
        }),
      });
      const data = await res.json();
      if (data.ok && data.forecast) {
        setForecast(data.forecast);
      } else {
        setError(data.detail || "No forecast generated. Try selecting a different target or time dimension.");
        setForecast(null);
      }
    } catch (e: any) {
      setError(e.message || "Failed to generate forecast");
      setForecast(null);
    } finally {
      setLoading(false);
    }
  }, [selectedTarget, selectedTime, horizon, columns, dateColumns]);

  // Auto-fetch on first load if no predictions from insightResult
  useEffect(() => {
    if (connectionStatus !== "connected") return;
    if (!hasInsightPredictions && (!forecast || forecast.points?.length === 0)) {
      // Small delay to allow schema info to load first
      const timer = setTimeout(() => fetchForecast(), 500);
      return () => clearTimeout(timer);
    }
  }, [connectionStatus, hasInsightPredictions, fetchForecast]);

  const predictions = forecast || insightPredictions;
  const hasPredictions = predictions && (predictions.valid || predictions.points?.length > 0);
  const forecastData = predictions?.points || [];
  const method = predictions?.method || "Auto-detected";
  const accuracy = predictions?.accuracy_pct || null;
  const reliability = predictions?.reliability || "medium";

  if (loading) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Predictive Analysis</h2>
        </div>
        <div className="mt-12 text-center py-12">
          <Loader2 size={32} className="animate-spin text-primary mx-auto mb-4" />
          <p className="text-sm text-muted-foreground">Analyzing time-series data and selecting forecasting model...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Predictive Analysis</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Understand what is likely to happen next.</p>
        </div>
        <button
          onClick={() => setShowControls(!showControls)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-secondary hover:bg-secondary/70 text-foreground text-xs font-medium border border-border transition-colors"
        >
          <SlidersHorizontal size={13} /> Controls
        </button>
      </div>

      {/* Forecast Configuration */}
      {showControls && (
        <div className="bg-card border border-border rounded-xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <SlidersHorizontal size={14} className="text-muted-foreground" />
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Forecast Configuration</p>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Metric</p>
              <div className="relative">
                <select
                  value={selectedTarget}
                  onChange={(e) => { setSelectedTarget(e.target.value); setForecast(null); }}
                  className="w-full appearance-none bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none transition-colors pr-8 cursor-pointer"
                >
                  <option value="">Select a measure...</option>
                  {columns.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              </div>
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Dataset</p>
              <div className="relative">
                <select
                  value={selectedTime}
                  onChange={(e) => { setSelectedTime(e.target.value); setForecast(null); }}
                  className="w-full appearance-none bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none transition-colors pr-8 cursor-pointer"
                >
                  <option value="">Auto-detect...</option>
                  {dateColumns.map((c) => (
                    <option key={c} value={c}>{c}</option>
                  ))}
                </select>
                <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              </div>
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Forecast Horizon</p>
              <div className="relative">
                <select
                  value={horizon}
                  onChange={(e) => { setHorizon(Number(e.target.value)); setForecast(null); }}
                  className="w-full appearance-none bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none transition-colors pr-8 cursor-pointer"
                >
                  {[3, 6, 12, 24].map((h) => (
                    <option key={h} value={h}>{h} periods</option>
                  ))}
                </select>
                <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              </div>
            </div>
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-muted-foreground">Granularity</p>
              <div className="relative">
                <select
                  value="auto"
                  onChange={() => {}}
                  className="w-full appearance-none bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground focus:border-primary outline-none transition-colors pr-8 cursor-pointer"
                >
                  <option value="auto">Auto-detect</option>
                </select>
                <ChevronDown size={12} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              </div>
            </div>
          </div>
          <div className="flex gap-2 pt-4">
            <button
              onClick={() => fetchForecast(selectedTarget || columns[0], selectedTime || dateColumns[0], horizon)}
              disabled={loading || !columns.length}
              className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
            >
              {loading ? "Analyzing..." : "Run Forecast"}
            </button>
            <button
              onClick={() => setForecast(null)}
              className="px-4 py-2 rounded-lg text-xs font-medium bg-secondary text-foreground hover:bg-secondary/70 border border-border transition-colors"
            >
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Refresh */}
      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          Target: <span className="font-medium text-foreground">{predictions?.column || selectedTarget || "Auto"}</span> ·
          Method: <span className="font-medium text-foreground">{method}</span>
        </span>
        <button
          onClick={() => fetchForecast(selectedTarget || columns[0], selectedTime || dateColumns[0], horizon)}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-secondary hover:bg-secondary/70 text-foreground transition-colors border border-border disabled:opacity-50"
          title="Refresh forecast"
        >
          <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      {/* Error */}
      {error && !hasPredictions && (
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <AlertCircle size={16} className="text-negative mt-0.5 flex-shrink-0" />
            <div className="space-y-2">
              <p className="text-sm text-negative font-medium">{error}</p>
              <p className="text-xs text-muted-foreground">Try selecting a different target or ensuring your data has time-series information.</p>
              <button onClick={() => fetchForecast()} className="text-xs text-primary hover:underline">Try automatic selection</button>
            </div>
          </div>
        </div>
      )}

      {/* Empty state when no predictions and no error */}
      {!hasPredictions && !loading && !error && (
        <div className="text-center py-12 bg-card border border-border rounded-xl">
          <TrendingUp size={32} className="text-muted-foreground mx-auto mb-3" />
          <p className="text-muted-foreground text-base">No predictions yet.</p>
          <p className="text-xs text-muted-foreground mt-1">Select a target measure and generate a forecast.</p>
          <button
            onClick={() => setShowControls(true)}
            className="mt-4 premium-btn btn-glow px-4 py-2 rounded-lg text-xs font-semibold text-white transition-all"
            style={{ background: "var(--gradient-primary)" }}
          >
            Configure Forecast
          </button>
        </div>
      )}

      {/* Accuracy Badge */}
      {hasPredictions && accuracy && (
        <div className="premium-card bg-card border border-border rounded-xl p-5 cursor-default">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-4 flex-wrap">
              <div>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Forecast Quality</p>
                <p className="text-sm font-semibold text-foreground">Backtest Accuracy</p>
                <p className="text-lg font-bold text-positive">{accuracy.toFixed(1)}%</p>
              </div>
              <div className="w-px h-10 bg-border hidden sm:block" />
              <div>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Model</p>
                <p className="text-sm font-semibold text-foreground">{method}</p>
              </div>
              <div className="w-px h-10 bg-border hidden sm:block" />
              <div>
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1">Reliability</p>
                <p className={`text-sm font-bold capitalize ${
                  reliability === "high" ? "text-positive" :
                  reliability === "medium" ? "text-warning" : "text-muted-foreground"
                }`}>{reliability}</p>
              </div>
            </div>
            {predictions?.valid && (
              <span className="text-xs font-semibold text-positive bg-positive/10 border border-positive/30 px-3 py-1 rounded-full whitespace-nowrap">
                Validated Forecast
              </span>
            )}
          </div>
        </div>
      )}

      {/* Forecast summary card */}
      {hasPredictions && (
        <div className="bg-card border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-foreground">Forecast Summary</h3>
            <span className="text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full">{forecastData.length} points · Horizon: {horizon}</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-secondary/40 rounded-lg p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Target</p>
              <p className="text-sm font-semibold text-foreground truncate">{predictions?.column || selectedTarget || "Auto-selected"}</p>
            </div>
            <div className="bg-secondary/40 rounded-lg p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Method</p>
              <p className="text-sm font-semibold text-foreground">{method}</p>
            </div>
            <div className="bg-secondary/40 rounded-lg p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Last Actual</p>
              <p className="text-sm font-semibold text-foreground">{predictions?.last_actual?.value ? predictions.last_actual.value.toFixed(2) : "N/A"}</p>
            </div>
            <div className="bg-secondary/40 rounded-lg p-3">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Projected Change</p>
              <p className={`text-sm font-bold ${predictions?.projected_pct_change > 0 ? "text-positive" : predictions?.projected_pct_change < 0 ? "text-negative" : "text-foreground"}`}>
                {predictions?.projected_pct_change !== null ? `${predictions.projected_pct_change > 0 ? "+" : ""}${predictions.projected_pct_change.toFixed(1)}%` : "N/A"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Main chart */}
      {hasPredictions && forecastData.length > 0 && (
        <div className="bg-card border border-border rounded-xl p-5">
          <div className="flex items-center justify-between mb-5">
            <div>
              <p className="text-sm font-semibold text-foreground">{predictions?.column || "Forecast"} — Forecast</p>
              <p className="text-xs text-muted-foreground mt-0.5">Historical data + forecast with confidence interval</p>
            </div>
            <div className="flex gap-4 text-xs text-muted-foreground items-center">
              <span className="flex items-center gap-1.5"><span className="w-4 h-0.5 bg-foreground inline-block rounded" /> Actual</span>
              <span className="flex items-center gap-1.5"><span className="w-4 h-0.5 border-t-2 border-dashed border-primary inline-block" /> Forecast</span>
              <span className="flex items-center gap-1.5"><span className="w-3 h-3 bg-primary/15 inline-block rounded" /> Confidence</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={forecastData}>
              <defs>
                <linearGradient id="confGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.1} />
                  <stop offset="95%" stopColor="var(--primary)" stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
              <XAxis dataKey={forecastData[0]?.label ? "label" : forecastData[0]?.date ? "date" : forecastData[0]?.period ? "period" : "label"} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
              <Tooltip
                contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow-md)" }}
                labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {predictions?.lower95 && <Area type="monotone" dataKey="lower95" stroke="none" fill="url(#confGrad)" name="95% Range" />}
              {predictions?.upper95 && <Area type="monotone" dataKey="upper95" stroke="none" fill="url(#confGrad)" />}
              <Line type="monotone" dataKey={forecastData[0]?.actual ? "actual" : "value"} stroke="var(--foreground)" strokeWidth={2} dot={{ r: 3 }} name="Historical" />
              <Line type="monotone" dataKey="forecast" stroke="var(--primary)" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 3 }} name="Forecast" />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ARIA Interpretation — only for validated forecasts; errors use the error block */}
      {hasPredictions && predictions?.valid && predictions?.reason && (
        <div className="bg-primary/5 border border-primary/20 rounded-xl p-5 space-y-2">
          <p className="text-xs font-semibold text-primary uppercase tracking-wider">ARIA Interpretation</p>
          <p className="text-sm text-foreground leading-relaxed">{predictions.reason}</p>
        </div>
      )}

      {/* Scenario Analysis — deterministic what-if on real aggregates */}
      <div className="bg-card border border-border rounded-xl p-5 space-y-4">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Scenario Analysis</p>
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground">Change to {selectedTarget.split(" (")[0] || "measure"} (%)</p>
            <input
              type="number" min={-95} max={95} step={1} value={scenarioPct}
              onChange={(e) => setScenarioPct(Number(e.target.value))}
              className="w-32 bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-primary transition-colors"
            />
          </div>
          <button
            onClick={runScenario}
            disabled={scenarioLoading}
            className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50"
          >
            {scenarioLoading ? "Calculating..." : "Run Scenario"}
          </button>
          <p className="text-[11px] text-muted-foreground w-full">Estimate only — uniform change on trailing actuals, not a forecast.</p>
        </div>
        {scenarioError && <p className="text-sm text-negative font-medium">{scenarioError}</p>}
        {scenario && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="border border-border rounded-xl p-4 space-y-1">
              <p className="text-xs text-muted-foreground">Baseline (trailing avg)</p>
              <p className="text-xl font-bold text-foreground">{Number(scenario.baseline).toLocaleString()}</p>
              <p className="text-xs text-muted-foreground">{scenario.periods_used} period(s) · {scenario.column}</p>
            </div>
            <div className="border border-primary/40 bg-primary/5 rounded-xl p-4 space-y-1">
              <p className="text-xs text-muted-foreground">Scenario ({scenario.pct_change > 0 ? "+" : ""}{scenario.pct_change}%)</p>
              <p className="text-xl font-bold text-foreground">{Number(scenario.scenario_value).toLocaleString()}</p>
              <p className={`text-xs font-semibold ${scenario.delta >= 0 ? "text-positive" : "text-negative"}`}>
                {scenario.delta >= 0 ? "+" : ""}{Number(scenario.delta).toLocaleString()} vs baseline
              </p>
            </div>
            <div className="border border-border rounded-xl p-4 space-y-1">
              <p className="text-xs text-muted-foreground">Assumptions</p>
              {(scenario.assumptions || []).map((a: string, i: number) => (
                <p key={i} className="text-xs text-foreground leading-relaxed">· {a}</p>
              ))}
              {scenario.limitations && <p className="text-[11px] text-muted-foreground pt-1">{scenario.limitations}</p>}
            </div>
          </div>
        )}
      </div>

      {/* Prediction intervals section */}
      {hasPredictions && predictions?.validation && (
        <div className="bg-card border border-border rounded-xl p-5">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Validation & Reliability</p>
          <div className="space-y-2 text-sm">
            <div className="flex justify-between">
              <span className="text-muted-foreground">Validation method</span>
              <span className="font-medium text-foreground">{predictions.validation?.method || "Walk-forward"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Backtest MAPE</span>
              <span className={`font-medium ${predictions.validation?.passed ? "text-positive" : "text-negative"}`}>
                {predictions.mape_pct !== null ? `${predictions.mape_pct.toFixed(1)}%` : "N/A"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Accuracy (100 - MAPE)</span>
              <span className="font-semibold text-foreground">{predictions.accuracy_pct !== null ? `${predictions.accuracy_pct.toFixed(1)}%` : "N/A"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Threshold</span>
              <span className="font-medium text-foreground">{predictions.validation?.threshold_pct || 70}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-muted-foreground">Passed</span>
              <span className={`font-bold ${predictions.validation?.passed ? "text-positive" : "text-negative"}`}>
                {predictions.validation?.passed ? "Yes" : "No"}
              </span>
            </div>
          </div>
          {predictions?.model_notes?.note && (
            <p className="text-xs text-muted-foreground mt-3 pt-3 border-t border-border">Note: {predictions.model_notes.note}</p>
          )}
        </div>
      )}
    </div>
  );
}
