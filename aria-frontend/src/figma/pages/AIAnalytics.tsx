import { useState, useRef, useEffect } from "react";
import { Search, X, Clock, Copy, ChevronDown, ChevronUp, Sparkles, ArrowRight,
CheckCircle, Loader2, Code2, Table2, AlertCircle, Database, GitBranch, HelpCircle, BookOpen } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, LineChart, Line, PieChart, Pie, Cell, ScatterChart, Scatter } from "recharts";
import { useTheme } from "../App";
import { colorForName } from "../lib/charts";

type AnalysisState = "idle" | "processing" | "done" | "clarification" | "error";

interface AIAnalyticsProps {
  initialQuery?: string;
  onAsk?: (question: string) => void;
  analysisResult?: any;
  goalStatus?: string;
  goalResult?: any;
  goalError?: string;
  loading?: boolean;
}

const CHART_COLORS = ["#4F46E5", "#059669", "#F59E0B", "#EC4899", "#06B6D4", "#8B5CF6", "#EF4444", "#14B8A6"];

// Dynamic suggestions from the actual analysis result — fully database-independent.
function getDynamicSuggestions(goalResult: any): string[] {
  const fromResult = goalResult?.suggestedQuestions || goalResult?.suggested_questions || [];
  if (fromResult.length > 0) {
    return fromResult.slice(0, 6);
  }
  return [
    "How many total records are in the connected data?",
    "What is the total of the main numeric measure?",
    "Which categories or segments appear most frequently?",
    "How has the key metric changed over time?",
    "What are the top items by value or quantity?",
    "What is the average of the primary measure?",
  ];
}

export default function AIAnalytics({
  initialQuery = "",
  onAsk,
  analysisResult = null,
  goalStatus = "idle",
  goalResult = null,
  goalError = "",
  loading = false,
}: AIAnalyticsProps) {
  const { isDark } = useTheme();
  const [query, setQuery] = useState(initialQuery);
  const [sqlExpanded, setSqlExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const [showWhy, setShowWhy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  // Derive state from props
  const state: AnalysisState =
    loading || goalStatus === "loading" ? "processing" :
    goalError ? "error" :
    goalResult?.clarificationRequired ? "clarification" :
    (analysisResult && (goalStatus === "success" || goalResult?.generatedSql)) ||
    (goalResult?.message && goalStatus === "success") ||
    (goalResult?.data && goalStatus === "success") ? "done" :
    "idle";

  const runAnalysis = (q?: string) => {
    const text = q || query;
    if (!text.trim()) return;
    setQuery(text);
    setChartOverride("");
    onAsk?.(text);
  };

  const copySQL = () => {
    const sql = goalResult?.generatedSql || goalResult?.sql_used || "";
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Extract real data from results
  const sqlUsed = goalResult?.generatedSql || goalResult?.sql_used || "";
  const tableData = goalResult?.data || analysisResult?.data || [];
  const chartData = tableData;
  const followUps = goalResult?.suggestedQuestions || goalResult?.suggested_questions || [];
  const backendSpec = goalResult?.chartSpec || null;
  const analysisMeta = goalResult?.analysis || null;

  // Feedback tracking (personalization layer — Section 62)
  const [insightRating, setInsightRating] = useState<"useful" | "not_useful" | null>(null);
  // User chart override: changing visualization records a preference so the
  // backend learns contextual chart taste (RL loop). Never overrides validity.
  const [chartOverride, setChartOverride] = useState("");
  const trackChartSwitch = async (toType: string) => {
    setChartOverride(toType);
    try {
      const token = localStorage.getItem("aria_auth_token");
      if (token) {
        const cols = Object.keys(chartData[0] || {}).sort().join("_");
        await fetch("/api/feedback/chart", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ chart_type: toType, context: cols || "general" }),
        });
      }
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };
  const trackSuggestionClick = async (text: string) => {
    try {
      const token = localStorage.getItem("aria_auth_token");
      if (token) {
        await fetch("/api/feedback/suggestion", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ suggestion_text: text, source: "analytics" }),
        });
      }
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };
  const rateInsight = async (rating: "useful" | "not_useful") => {
    setInsightRating(rating);
    try {
      const token = localStorage.getItem("aria_auth_token");
      if (token) {
        await fetch("/api/feedback/insight", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            question: goalResult?.question || query,
            rating,
            category: "analytics",
          }),
        });
      }
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };

  // Determine chart plan from data shape, preferring the backend registry
  // spec (chartSpec) when the shape genuinely supports it — never forcing.
  const getChartPlan = () => {
    if (!chartData.length) return null;
    const keys = Object.keys(chartData[0]);
    const dateKeys = keys.filter(k => /date|time|month|year|period|day/i.test(k));
    const numKeys = keys.filter(k => {
      const v = chartData[0]?.[k];
      return typeof v === "number" || (typeof v === "string" && v !== "" && !isNaN(Number(v)));
    });
    const catKeys = keys.filter(k => !dateKeys.includes(k) && !numKeys.includes(k));
    const pickNum = (exclude: string[] = []) =>
      numKeys.find(k => !exclude.includes(k)) || "";
    const specType = goalResult?.chartSpec?.chart_type || "";

    // Two numerics → scatter (backend "relationship" shape).
    if (numKeys.length >= 2 && !dateKeys.length && !catKeys.length) {
      if (["scatter", "hexbin", "contour", "bubble"].includes(specType)
          || !["bar", "pie", "line", "area"].includes(specType)) {
        return { type: "scatter", data: chartData, xKey: numKeys[0], yKey: numKeys[1], series: [] as string[] };
      }
    }
    // Single numeric, no categories → histogram (client-side binning of real values).
    if (numKeys.length >= 1 && !catKeys.length && !dateKeys.length) {
      const col = numKeys[0];
      const vals = chartData.map(r => Number(r[col])).filter(v => !isNaN(v));
      if (vals.length >= 5) {
        const lo = Math.min(...vals), hi = Math.max(...vals);
        const bins = Math.max(4, Math.min(12, Math.round(Math.sqrt(vals.length))));
        const width = (hi - lo) / bins || 1;
        const counts = new Array(bins).fill(0);
        vals.forEach(v => {
          const i = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / width)));
          counts[i]++;
        });
        const data = counts.map((c, i) => ({
          bin: `${(lo + i * width).toFixed(1)}–${(lo + (i + 1) * width).toFixed(1)}`,
          count: c,
        }));
        return { type: "histogram", data, xKey: "bin", yKey: "count", series: [] as string[] };
      }
    }
    // Time + numeric → area/line.
    if (dateKeys.length && numKeys.length) {
      const t = (specType === "line" || specType === "step_line" || specType === "sparkline") ? "line" : "area";
      return { type: t, data: chartData, xKey: dateKeys[0], yKey: pickNum(), series: [] as string[] };
    }
    // Category + 2 numerics → stacked bar.
    if (catKeys.length && numKeys.length >= 2) {
      return { type: "stacked", data: chartData.slice(0, 10), xKey: catKeys[0], yKey: numKeys[0], series: numKeys.slice(0, 3) };
    }
    // Category + numeric → bar (horizontal for long labels / many cats).
    if (catKeys.length && numKeys.length) {
      const labels = chartData.map(r => String(r[catKeys[0]] ?? ""));
      const avgLen = labels.reduce((a, s) => a + s.length, 0) / Math.max(1, labels.length);
      const horizontal = chartData.length > 8 || avgLen > 14;
      const preferPie = ["pie", "doughnut", "donut", "polar_area"].includes(specType)
        && chartData.length <= 6;
      if (preferPie) return { type: "pie", data: chartData, xKey: catKeys[0], yKey: pickNum(), series: [] as string[] };
      return { type: horizontal ? "hbar" : "bar", data: horizontal ? chartData.slice(0, 12) : chartData, xKey: catKeys[0], yKey: pickNum(), series: [] as string[] };
    }
    // Single category (counts) → bar of frequencies.
    if (catKeys.length) {
      const freq: Record<string, number> = {};
      chartData.forEach(r => { const k = String(r[catKeys[0]] ?? "—"); freq[k] = (freq[k] || 0) + 1; });
      const data = Object.entries(freq).map(([name, value]) => ({ name, value }))
        .sort((a, b) => b.value - a.value).slice(0, 10);
      return { type: "bar", data, xKey: "name", yKey: "value", series: [] as string[] };
    }
    return { type: "bar", data: chartData, xKey: keys[0], yKey: pickNum([keys[0]]), series: [] as string[] };
  };

  const chartPlan = getChartPlan();
  // Backend registry names → locally renderable families.
  const mapBackendType = (t: string): string | null => {
    const v = (t || "").toLowerCase();
    if (["line", "step_line", "sparkline", "slope", "multi_line", "control_chart"].includes(v)) return "line";
    if (["area", "stacked_area", "density", "ecdf", "calendar_heatmap"].includes(v)) return "area";
    if (["bar_horizontal"].includes(v)) return "hbar";
    if (["bar_stacked", "bar_grouped", "bar_normalized", "combo", "heatmap"].includes(v)) return "stacked";
    if (["bar", "bar_diverging", "lollipop", "pareto", "waterfall", "funnel", "bullet"].includes(v)) return "bar";
    if (["pie", "doughnut", "donut", "polar_area", "gauge"].includes(v)) return "pie";
    if (["scatter", "hexbin", "contour", "bubble"].includes(v)) return "scatter";
    if (["histogram"].includes(v)) return "histogram";
    if (["kpi_card"].includes(v)) return "bar";
    return null;
  };
  const _autoType = chartPlan?.type || "bar";
  const _compatTypes: string[] = [
    ...(goalResult?.chartSpec?.compatible || []),
    goalResult?.chartSpec?.chart_type || "",
  ];
  const chartOptions: string[] = [];
  [_autoType, ..._compatTypes].forEach((t) => {
    const m = mapBackendType(t);
    if (m && !chartOptions.includes(m)) chartOptions.push(m);
  });
  if (!chartOptions.includes(_autoType)) chartOptions.unshift(_autoType);
  const chartType = chartOverride && chartOptions.includes(chartOverride) ? chartOverride : _autoType;
  const xKey = chartPlan?.xKey || "";
  const yKey = chartPlan?.yKey || "";
  const chartSeries: string[] = chartPlan?.series || [];
  const chartRenderData = chartPlan?.data || chartData;

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">AI Analytics</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Ask questions. Explore your data. Get answers.</p>
      </div>

      {/* Query Composer */}
      <div className="space-y-3">
        <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3.5 focus-within:border-primary/50 focus-within:shadow-[0_0_0_3px_var(--primary-light)] transition-all duration-200" style={{ boxShadow: 'var(--shadow-sm)' }}>
          <Sparkles size={16} className="text-primary flex-shrink-0" />
            <input
              ref={inputRef}
              value={query}
              aria-label="Ask ARIA a business question"
              onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !loading && runAnalysis()}
            placeholder="How many records? What is the total? Which categories rank highest? How has the metric changed over time?"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
            disabled={loading}
          />
          {query && (
            <button onClick={() => { setQuery(""); }} className="text-muted-foreground hover:text-foreground transition-colors">
              <X size={15} />
            </button>
          )}
          <button
            onClick={() => runAnalysis()}
            disabled={loading || !query.trim()}
            className="premium-btn btn-glow flex-shrink-0 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'var(--gradient-primary)' }}
          >
            {loading ? "Analyzing..." : "Analyze"}
          </button>
        </div>

        {/* Suggested queries */}
        {state === "idle" && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5"><Clock size={11} /> Try asking</p>
            <div className="flex flex-wrap gap-2">
              {getDynamicSuggestions(goalResult).map((q) => (
                <button
                  key={q}
                  onClick={() => runAnalysis(q)}
                  className="text-xs px-3 py-1.5 bg-secondary hover:bg-secondary/70 border border-border rounded-full text-muted-foreground hover:text-foreground transition-colors truncate max-w-xs"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Processing — stages reflect real lifecycle milestones, never timers:
          engine working (no result yet) vs finalizing visualization (result arrived) */}
      {state === "processing" && (
        <div className="bg-card border border-border rounded-xl p-6 flex flex-col items-center gap-5">
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
            <Loader2 size={20} className="text-primary animate-spin" />
          </div>
          <div className="text-center space-y-1">
            <p className="text-sm font-medium text-foreground">
              {goalResult ? "Preparing visualization..." : "Understanding your question..."}
            </p>
            <p className="text-xs text-muted-foreground">
              {goalResult
                ? "Analysis received, building charts and supporting data"
                : "Inspecting data and generating analysis against real data"}
            </p>
          </div>
          <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
            <span className={goalResult ? "text-positive" : "text-primary font-medium"}>● Understand</span>
            <span>→</span>
            <span className={goalResult ? "text-primary font-medium" : ""}>● Visualize</span>
            <span>→</span>
            <span>○ Result</span>
          </div>
        </div>
      )}

      {/* Error */}
      {goalError && state === "error" && (
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <AlertCircle size={16} className="text-negative mt-0.5 flex-shrink-0" />
            <div className="space-y-2">
              <p className="text-sm text-negative font-medium">{goalError}</p>
              <button
                onClick={() => runAnalysis()}
                className="text-xs text-negative/80 hover:text-negative underline transition-colors"
              >
                Try again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Clarification */}
      {state === "clarification" && goalResult?.clarificationMessage && (
        <div className="bg-card border border-border rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
              <Sparkles size={12} className="text-primary" />
            </div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Clarification needed</p>
          </div>
          <p className="text-sm text-foreground leading-relaxed">{goalResult.clarificationMessage}</p>
          <div className="flex flex-wrap gap-2 pt-1">
            {["total sales by month", "top products", "revenue by category"].map((q) => (
              <button
                key={q}
                onClick={() => runAnalysis(q)}
                className="text-xs px-3 py-1.5 bg-secondary hover:bg-secondary/70 border border-border rounded-full text-muted-foreground hover:text-foreground transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      {state === "done" && (
        <div className="space-y-4">
          {/* Answer */}
          {goalResult?.message && (
            <div className="premium-card bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                  <Sparkles size={12} className="text-primary" />
                </div>
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Answer</p>
              </div>
              <p className="text-[14px] font-medium text-foreground leading-relaxed">
                {goalResult.message}
              </p>
              <div className="flex flex-wrap gap-4 pt-1 text-[11px] text-muted-foreground">
                {analysisMeta?.based_on > 0 && (
                  <span>
                    Based on{" "}
                    <span className="text-foreground font-medium">
                      {analysisMeta.based_on.toLocaleString()}
                    </span>{" "}
                    records
                  </span>
                )}
                {analysisMeta?.entity_count > 0 && (
                  <span>
                    <span className="text-foreground font-medium">
                      {analysisMeta.entity_count}
                    </span>{" "}
                    {analysisMeta.entity
                      ? (analysisMeta.entity_count === 1 ? analysisMeta.entity : `${analysisMeta.entity}s`)
                      : "groups"}{" "}
                    analyzed
                  </span>
                )}
                {(goalResult.confidence || analysisMeta?.confidence) && (
                  <span>
                    Confidence:{" "}
                    <span className="text-positive font-medium">
                      {goalResult.confidence || analysisMeta.confidence}
                    </span>
                  </span>
                )}
              </div>
              {/* Feedback buttons — personalization signal (Section 62) */}
              <div className="flex items-center gap-2 pt-2 border-t border-border">
                <span className="text-[11px] text-muted-foreground">Was this helpful?</span>
                <button
                  onClick={() => rateInsight("useful")}
                  className={`px-2 py-0.5 text-[11px] rounded-md border transition-colors ${insightRating === "useful" ? "bg-positive/10 border-positive/30 text-positive" : "border-border text-muted-foreground hover:text-foreground hover:border-primary/30"}`}
                >
                  Yes
                </button>
                <button
                  onClick={() => rateInsight("not_useful")}
                  className={`px-2 py-0.5 text-[11px] rounded-md border transition-colors ${insightRating === "not_useful" ? "bg-destructive/10 border-destructive/30 text-destructive" : "border-border text-muted-foreground hover:text-foreground hover:border-primary/30"}`}
                >
                  No
                </button>
              </div>
            </div>
          )}

          {/* Visualization */}
          {chartRenderData.length > 0 && xKey && yKey && (
            <div className="bg-card border border-border rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Visualization</p>
                <div className="flex items-center gap-2">
                  {goalResult?.chartSpec?.reason && (
                    <p className="text-[10px] text-muted-foreground hidden md:block" title={goalResult.chartSpec.reason}>
                      {goalResult.chartSpec.label || chartType}
                    </p>
                  )}
                  {chartOptions.length > 1 && (
                    <select
                      value={chartType}
                      aria-label="Change chart type"
                      onChange={(e) => trackChartSwitch(e.target.value)}
                      className="text-[11px] bg-secondary border border-border rounded-lg px-2 py-1 text-foreground outline-none focus:border-primary cursor-pointer"
                    >
                      {chartOptions.map((t) => (
                        <option key={t} value={t}>
                          {t === "hbar" ? "Horizontal bar" : t === "stacked" ? "Stacked bar" : t[0].toUpperCase() + t.slice(1)}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </div>
              <ResponsiveContainer width="100%" height={260}>
                {chartType === "area" || chartType === "line" ? (
                  <AreaChart data={chartRenderData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    />
                    <Area type="monotone" dataKey={yKey} stroke="#4F46E5" fill="#4F46E5" fillOpacity={0.15} strokeWidth={2} />
                  </AreaChart>
                ) : chartType === "scatter" ? (
                  <ScatterChart>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey={xKey} name={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis dataKey={yKey} name={yKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      cursor={{ strokeDasharray: "3 3" }}
                    />
                    <Scatter data={chartRenderData} fill="#4F46E5" fillOpacity={0.6} />
                  </ScatterChart>
                ) : chartType === "hbar" ? (
                  <BarChart data={chartRenderData} layout="vertical" barSize={22}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={110} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    />
                    <Bar dataKey={yKey} radius={[0, 5, 5, 0]}>
                      {chartRenderData.map((row: any, i: number) => (
                        <Cell key={i} fill={colorForName(String(row?.[xKey] ?? i))} />
                      ))}
                    </Bar>
                  </BarChart>
                ) : chartType === "stacked" ? (
                  <BarChart data={chartRenderData} barSize={28}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    />
                    {chartSeries.map((s, i) => (
                      <Bar key={s} dataKey={s} stackId="a" fill={CHART_COLORS[i % CHART_COLORS.length]} radius={i === chartSeries.length - 1 ? [5, 5, 0, 0] : [0, 0, 0, 0]} />
                    ))}
                  </BarChart>
                ) : chartType === "pie" ? (
                  <PieChart>
                    <Pie
                      data={chartRenderData}
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      dataKey={yKey}
                      nameKey={xKey}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {chartRenderData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                    />
                  </PieChart>
                ) : (
                  <BarChart data={chartRenderData} barSize={36}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    />
                    <Bar dataKey={yKey} radius={[5, 5, 0, 0]}>
                      {chartRenderData.map((row: any, i: number) => (
                        <Cell
                          key={i}
                          fill={chartType === "histogram" ? "#4F46E5" : colorForName(String(row?.[xKey] ?? i))}
                          fillOpacity={chartType === "histogram" ? 0.55 + (0.45 * i) / Math.max(1, chartRenderData.length) : 1}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                )}
              </ResponsiveContainer>
            </div>
          )}

          {/* Why? — stored structured explanation (§21), shown on demand */}
          {goalResult?.why && (
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <button
                onClick={() => setShowWhy((w) => !w)}
                className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-secondary/40 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <HelpCircle size={14} className="text-primary" />
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Why this result?</p>
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                    {goalResult.why.confidence} confidence
                  </span>
                </div>
                {showWhy ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
              </button>
              {showWhy && (
                <div className="border-t border-border px-5 py-4 space-y-3">
                  <div>
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">What happened</p>
                    <p className="text-sm text-foreground leading-relaxed">{goalResult.why.what_happened}</p>
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Why it matters</p>
                    <p className="text-sm text-foreground leading-relaxed">{goalResult.why.why_it_matters}</p>
                  </div>
                  {goalResult.why.contributing_factors?.length > 0 && (
                    <div>
                      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Contributing factors</p>
                      <p className="text-sm text-foreground">{goalResult.why.contributing_factors.join(", ")}</p>
                    </div>
                  )}
                  {goalResult.why.limitations?.length > 0 && (
                    <div className="bg-secondary/40 rounded-lg p-3">
                      <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1">Limitations</p>
                      {goalResult.why.limitations.map((lim: string, i: number) => (
                        <p key={i} className="text-xs text-muted-foreground leading-relaxed">· {lim}</p>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Story — coherent evidence-based narrative (§23) */}
          {goalResult?.story && (
            <div className="bg-primary/5 border border-primary/20 rounded-xl p-5 space-y-2">
              <div className="flex items-center gap-2">
                <BookOpen size={14} className="text-primary" />
                <p className="text-xs font-semibold text-primary uppercase tracking-wider">Data Story</p>
              </div>
              <p className="text-sm text-foreground leading-relaxed">{goalResult.story}</p>
            </div>
          )}


          {/* Table */}
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <button
              onClick={() => setShowTable((t) => !t)}
              className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-secondary/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <Table2 size={14} className="text-muted-foreground" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Supporting Data</p>
                {tableData.length > 0 && (
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{tableData.length} rows</span>
                )}
              </div>
              {showTable ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
            </button>
            {showTable && tableData.length > 0 && (
              <div className="border-t border-border overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border">
                      {Object.keys(tableData[0]).map((h) => (
                        <th key={h} className="text-left text-xs font-medium text-muted-foreground px-5 py-3 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.slice(0, 50).map((row, i) => (
                      <tr key={i} className={`${i < Math.min(tableData.length, 50) - 1 ? "border-b border-border" : ""} hover:bg-secondary/30 transition-colors`}>
                        {Object.values(row).map((val: any, j) => (
                          <td key={j} className="px-5 py-3 text-foreground whitespace-nowrap">
                            {typeof val === "number" ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(val) : String(val ?? "—")}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* SQL */}
          {sqlUsed && (
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <button
                onClick={() => setSqlExpanded((e) => !e)}
                className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-secondary/40 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Code2 size={14} className="text-muted-foreground" />
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Generated SQL</p>
                </div>
                {sqlExpanded ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
              </button>
              {sqlExpanded && (
                <div className="border-t border-border">
                  <div className="flex items-center justify-between px-4 py-2 bg-muted/60">
                    <span className="text-xs text-muted-foreground font-mono">SQL Query</span>
                    <div className="flex gap-2">
                      <button onClick={copySQL} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                        {copied ? <><CheckCircle size={12} className="text-positive" /> Copied!</> : <><Copy size={12} /> Copy</>}
                      </button>
                      <button
                        onClick={() => { const q = `Explain what this SQL query does in business terms: ${sqlUsed}`; setQuery(q); runAnalysis(q); }}
                        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <Sparkles size={12} /> Explain
                      </button>
                    </div>
                  </div>
                  <pre className="font-mono text-xs text-foreground px-5 py-4 overflow-x-auto leading-relaxed bg-muted/30">
                    <code>{sqlUsed}</code>
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* Follow-ups */}
          {followUps.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Continue your analysis</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 stagger-children">
                {followUps.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => { trackSuggestionClick(q); setQuery(q); runAnalysis(q); }}
                    className="premium-card flex items-center justify-between bg-card border border-border rounded-xl px-4 py-3 hover:border-primary/40 text-left group"
                  >
                    <p className="text-sm text-foreground group-hover:text-primary transition-colors">{q}</p>
                    <ArrowRight size={13} className="text-muted-foreground group-hover:text-primary transition-colors ml-2 flex-shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Provenance — source, table, column, SQL trace */}
          {goalResult?.provenance && (
            <div className="bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <GitBranch size={14} className="text-muted-foreground" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Source & Provenance</p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div className="space-y-1">
                  <p className="text-muted-foreground">Source</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.source || "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Type</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.source_type || "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Tables</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.tables?.join(", ") || "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Rows</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.row_count?.toLocaleString() || "—"}</p>
                </div>
              </div>
              {goalResult.provenance.columns?.length > 0 && (
                <div className="text-xs">
                  <p className="text-muted-foreground mb-1">Columns used</p>
                  <div className="flex flex-wrap gap-1.5">
                    {goalResult.provenance.columns.map((col: string) => (
                      <span key={col} className="px-2 py-0.5 bg-muted rounded text-foreground">{col}</span>
                    ))}
                  </div>
                </div>
              )}
              {goalResult.provenance.join_path?.length > 0 && (
                <div className="text-xs">
                  <p className="text-muted-foreground mb-1">Join path</p>
                  <p className="text-foreground font-mono text-[11px]">
                    {goalResult.provenance.join_path.map((j: any) => `${j.from}.${j.from_col} = ${j.to}.${j.to_col}`).join(" → ")}
                  </p>
                </div>
              )}
              {goalResult.provenance.document_evidence?.length > 0 && (
                <div className="text-xs space-y-2">
                  <p className="text-muted-foreground mb-1">Related documents</p>
                  {goalResult.provenance.document_evidence.map((d: any, i: number) => (
                    <div key={i} className="bg-secondary/40 border border-border rounded-lg p-2.5">
                      <p className="text-foreground leading-relaxed">{d.excerpt}</p>
                      <p className="text-[10px] text-muted-foreground mt-1">
                        Document {String(d.document_id).slice(0, 8)}{d.page ? ` · page ${d.page}` : ""}
                      </p>
                    </div>
                  ))}
                </div>
              )}
              {goalResult.conversationId && (
                <div className="flex items-center gap-4 text-[11px] text-muted-foreground pt-1 border-t border-border">
                  <span>Conversation: {goalResult.conversationId.split("_").slice(-1)[0]}</span>
                  {goalResult.turnNumber && <span>Turn: {goalResult.turnNumber}</span>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
