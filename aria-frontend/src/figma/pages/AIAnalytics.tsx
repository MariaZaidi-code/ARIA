import { useState, useRef, useEffect } from "react";
import { Search, X, Clock, ChevronDown, ChevronUp, Sparkles, ArrowRight,
Table2, AlertCircle, Database, HelpCircle, BookOpen, TrendingUp, Lightbulb } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, LineChart, Line, PieChart, Pie, Cell, ScatterChart, Scatter } from "recharts";
import { useTheme } from "../App";
import { colorForName, CATEGORY_COLORS } from "../lib/charts";
import { BizTooltip } from "../components/charts";
import AIProcessingIndicator from "../components/AIProcessingIndicator";
import { saveAnalysisContext, gotoWithContext } from "../lib/analysisContext";
import { API_BASE } from "../../services/api";

type AnalysisState = "idle" | "processing" | "done" | "clarification" | "error";

interface AIAnalyticsProps {
  initialQuery?: string;
  onAsk?: (question: string) => void;
  analysisResult?: any;
  goalStatus?: string;
  goalResult?: any;
  goalError?: string;
  loading?: boolean;
  onNavigate?: (page: string) => void;
  onAskCopilot?: (question: string) => void;
}

const CHART_COLORS = CATEGORY_COLORS;

// Dynamic suggestions from the actual analysis result — fully database-independent.
function getDynamicSuggestions(goalResult: any): string[] {
  const fromResult = goalResult?.followUpQuestions || goalResult?.follow_up_questions
    || goalResult?.suggestedQuestions || goalResult?.suggested_questions || [];
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
  onNavigate,
  onAskCopilot,
}: AIAnalyticsProps) {
  const { isDark } = useTheme();
  const [query, setQuery] = useState(initialQuery);
  const [showTable, setShowTable] = useState(false);
  const [showWhy, setShowWhy] = useState(false);
  const [showEvidence, setShowEvidence] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  // Data-aware autocomplete (GET /api/autocomplete, same pattern as Dashboard).
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const debounceRef = useRef<any>(null);

  const fetchAutocomplete = async (partial: string) => {
    try {
      const res = await fetch(`${API_BASE}/autocomplete?partial=${encodeURIComponent(partial)}&limit=6`, {
        credentials: "include",
      });
      if (!res.ok) { setSuggestions([]); return; }
      const data = await res.json();
      const list = Array.isArray(data?.suggestions)
        ? data.suggestions.map((s: any) => typeof s === "string" ? s : s.text).filter(Boolean)
        : [];
      setSuggestions(list);
      setActiveIndex(-1);
    } catch {
      setSuggestions([]);
    }
  };

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const partial = query || "";
    // Only hit the backend once the user typed something; empty query
    // keeps the static "Try asking" chips below.
    if (!partial.trim()) { setSuggestions([]); return; }
    debounceRef.current = setTimeout(() => fetchAutocomplete(partial), 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  // Derive state from props
  const state: AnalysisState =
    loading || goalStatus === "loading" ? "processing" :
    goalError ? "error" :
    goalResult?.clarificationRequired ? "clarification" :
    (analysisResult && (goalStatus === "success" || goalResult?.generatedSql)) ||
    ((goalResult?.answer || goalResult?.message) && goalStatus === "success") ||
    (goalResult?.data && goalStatus === "success") ? "done" :
    "idle";

  const runAnalysis = (q?: string) => {
    const text = q || query;
    if (!text.trim()) return;
    setQuery(text);
    setChartOverride("");
    onAsk?.(text);
  };


  // Extract real data from results (no raw SQL/provenance rendered — backend only).
  // Stable analytics contract fields are rendered as-is; missing keys render
  // as empty states, never fabricated client-side.
  const visualization = goalResult?.visualization || null;
  const tableData = (visualization?.data?.length ? visualization.data : null)
    || goalResult?.data || analysisResult?.data || [];
  const chartData = tableData;
  const followUps = (goalResult?.followUpQuestions?.length ? goalResult.followUpQuestions : null)
    || goalResult?.follow_up_questions || goalResult?.suggestedQuestions || goalResult?.suggested_questions || [];
  const backendSpec = goalResult?.chartSpec || null;
  const analysisMeta = goalResult?.analysis || null;
  const answer = goalResult?.answer || goalResult?.message || "";
  const findings: any[] = Array.isArray(goalResult?.findings) ? goalResult.findings : [];
  const evidenceList: any[] = Array.isArray(goalResult?.evidence) ? goalResult.evidence : [];
  const limitations: any[] = Array.isArray(goalResult?.limitations) ? goalResult.limitations : [];
  const possibleDrivers: any[] = Array.isArray(goalResult?.possibleDrivers)
    ? goalResult.possibleDrivers
    : (Array.isArray(goalResult?.possible_drivers) ? goalResult.possible_drivers : []);
  const hypothesisObj = goalResult?.hypothesis || null;
  const recommendationsList: any[] = Array.isArray(goalResult?.recommendations) ? goalResult.recommendations : [];
  const comparisonPeriod = goalResult?.comparisonPeriod || goalResult?.comparison_period || null;
  const resultStatus: string = goalResult?.resultStatus || goalResult?.result_status || "";
  const resultMessage: string = goalResult?.resultMessage || goalResult?.result_message || "";
  const interpreted = goalResult?.interpretedIntent || goalResult?.interpreted_intent || null;

  // Feedback tracking (personalization layer — Section 62)
  const [insightRating, setInsightRating] = useState<"useful" | "not_useful" | null>(null);
  // User chart override: changing visualization records a preference so the
  // backend learns contextual chart taste (RL loop). Never overrides validity.
  const [chartOverride, setChartOverride] = useState("");
  const trackChartSwitch = async (toType: string) => {
    setChartOverride(toType);
    try {
      const cols = Object.keys(chartData[0] || {}).sort().join("_");
      await fetch(`${API_BASE}/feedback/chart`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ chart_type: toType, context: cols || "general" }),
      });
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };
  const trackSuggestionClick = async (text: string) => {
    try {
      await fetch(`${API_BASE}/feedback/suggestion`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ suggestion_text: text, source: "analytics" }),
      });
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };
  const rateInsight = async (rating: "useful" | "not_useful") => {
    setInsightRating(rating);
    try {
      await fetch(`${API_BASE}/feedback/insight`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          question: goalResult?.question || query,
          rating,
          category: "analytics",
        }),
      });
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
    const specType = goalResult?.display?.chart?.type || goalResult?.chartSpec?.chart_type || "";
    const vizType = String(visualization?.type || "").toLowerCase();
    const vizX = visualization?.x && keys.includes(visualization.x) ? visualization.x : null;
    const vizY = visualization?.y && keys.includes(visualization.y) ? visualization.y : null;
    // Contract-first overrides: the backend intent determines the family.
    if (vizType === "scatter" && numKeys.length >= 2) {
      return { type: "scatter", data: chartData, xKey: vizX || numKeys[0], yKey: vizY || numKeys[1], series: [] as string[] };
    }
    if (vizType === "histogram" && numKeys.length >= 1) {
      const col = (vizY && numKeys.includes(vizY) ? vizY : numKeys[0]);
      const hvals = chartData.map(r => Number(r[col])).filter(v => !isNaN(v));
      if (hvals.length >= 5) {
        const hlo = Math.min(...hvals), hhi = Math.max(...hvals);
        const hb = Math.max(4, Math.min(12, Math.round(Math.sqrt(hvals.length))));
        const hw = (hhi - hlo) / hb || 1;
        const hc = new Array(hb).fill(0);
        hvals.forEach(v => {
          const i = Math.min(hb - 1, Math.max(0, Math.floor((v - hlo) / hw)));
          hc[i]++;
        });
        return { type: "histogram", data: hc.map((c, i) => ({
          bin: `${(hlo + i * hw).toFixed(1)}–${(hlo + (i + 1) * hw).toFixed(1)}`, count: c,
        })), xKey: "bin", yKey: "count", series: [] as string[] };
      }
    }
    if ((vizType === "line" || vizType === "area") && (dateKeys.length || numKeys.length || catKeys.length)) {
      const xk = vizX || dateKeys[0] || catKeys[0] || keys[0];
      return { type: vizType === "area" ? "area" : "line", data: chartData, xKey: xk, yKey: vizY || pickNum([xk]), series: [] as string[] };
    }
    if ((vizType === "comparison" || vizType === "stacked") && catKeys.length && numKeys.length) {
      const xk = vizX || catKeys[0];
      if (vizType === "stacked" && numKeys.length >= 2) {
        return { type: "stacked", data: chartData.slice(0, 10), xKey: xk, yKey: numKeys[0], series: numKeys.slice(0, 3) };
      }
      return { type: "bar", data: chartData.slice(0, 12), xKey: xk, yKey: vizY || pickNum(), series: [] as string[] };
    }
    if ((vizType === "h-bar" || vizType === "bar") && catKeys.length && numKeys.length) {
      const xk = vizX || catKeys[0];
      const horizontal = vizType === "h-bar" || chartData.length > 8;
      return { type: horizontal ? "hbar" : "bar", data: horizontal ? chartData.slice(0, 12) : chartData, xKey: xk, yKey: vizY || pickNum(), series: [] as string[] };
    }

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

  const contextQuestion = query || (goalResult as any)?.interpretedGoal || "";
  const goRelatedInsights = () => {
    saveAnalysisContext({
      origin: "analytics",
      question: contextQuestion,
      metric: analysisMeta?.entity || yKey || null,
      dimension: xKey || null,
      table: (goalResult?.relevantTables || [])[0] || null,
    });
    try {
      sessionStorage.setItem("aria_insight_handoff", JSON.stringify({
        origin: "analytics", question: contextQuestion,
        metric: analysisMeta?.entity || yKey || null,
      }));
    } catch { /* best-effort */ }
    gotoWithContext("insights", {});
  };
  const goCopilotAnalysis = () => {
    saveAnalysisContext({
      origin: "analytics",
      question: contextQuestion,
      metric: analysisMeta?.entity || yKey || null,
      dimension: xKey || null,
      table: (goalResult?.relevantTables || [])[0] || null,
    });
    if (onAskCopilot) onAskCopilot(contextQuestion || "Continue this analysis");
    else gotoWithContext("copilot", {});
  };
  const goHistory = () => {
    // History rows persist server-side on every /api/ask; this opens them.
    gotoWithContext("history", {});
  };
  const goPage = (p: string) => {
    if (onNavigate) {
      try { onNavigate(p); return; } catch { /* fall through to hash */ }
    }
    gotoWithContext(p, {});
  };

  // Lifecycle-driven AI stage (real milestones only, never timers):
  // 0 = request in flight, no payload yet · 1 = goal payload arrived,
  // evidence building · 2 = evidence ready, finalizing visualization.
  // Stage 3 ("Generating visualization") is the chart-reveal itself on done.
  const aiStage = !goalResult ? 0 : !analysisResult ? 1 : 2;
  // Chart-click drill selection: Investigate / Explain / Forecast
  // hooks travel with the shared analysis context.
  const [drill, setDrill] = useState<{ label: string; value: any } | null>(null);

  // Persist cross-module context on every successful analysis so Forecast
  // opens preselected via the shared context
  // (never re-analyzing); the hypothesis capability is embedded here
  // as Possible drivers instead of a standalone page.
  const submittedQ = (goalResult as any)?.interpretedGoal || "";
  useEffect(() => {
    if (state === "done" && (goalResult || analysisResult)) {
      const cols = Object.keys(chartData[0] || {});
      saveAnalysisContext({
        origin: "analytics",
        question: submittedQ || query,
        metric: yKey || null,
        dimension: xKey || null,
        table: (goalResult?.relevantTables || [])[0] || null,
        filters: null,
        source: goalResult?.relevantTables?.length
          ? { tables: goalResult.relevantTables, columns: cols }
          : null,
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state]);

  const drillHooks = (label: string) => {
    saveAnalysisContext({
      origin: "analytics-chart",
      question: query || submittedQ,
      metric: yKey || null,
      dimension: xKey || null,
      table: (goalResult?.relevantTables || [])[0] || null,
      segment: label || null,
    });
  };

  const onChartClick = (st: any) => {
    const p = st?.activePayload?.[0]?.payload;
    if (!p || !xKey) return;
    const label = String(p?.[xKey] ?? "");
    if (!label) return;
    const value = yKey ? p?.[yKey] : null;
    setDrill({ label, value });
    drillHooks(label);
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">AI Analytics</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Ask questions. Explore your data. Get answers.</p>
      </div>

      {/* Query Composer */}
      <div className="space-y-3">
        <div className="relative">
          <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3.5 focus-within:border-primary/50 focus-within:shadow-[0_0_0_3px_var(--primary-light)] transition-all duration-200" style={{ boxShadow: 'var(--shadow-sm)' }}>
            <Sparkles size={16} className="text-primary flex-shrink-0" />
              <input
                ref={inputRef}
                value={query}
                aria-label="Ask ARIA a business question"
                onChange={(e) => setQuery(e.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onKeyDown={(e) => {
                if (e.key === "ArrowDown" && suggestions.length > 0) {
                  e.preventDefault();
                  setShowSuggestions(true);
                  setActiveIndex((i) => (i + 1) % suggestions.length);
                } else if (e.key === "ArrowUp" && suggestions.length > 0) {
                  e.preventDefault();
                  setActiveIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
                } else if (e.key === "Escape") {
                  setShowSuggestions(false);
                } else if (e.key === "Enter") {
                  if (showSuggestions && activeIndex >= 0 && suggestions[activeIndex] && !loading) {
                    e.preventDefault();
                    runAnalysis(suggestions[activeIndex]);
                    setShowSuggestions(false);
                  } else if (!loading) {
                    runAnalysis();
                  }
                }
              }}
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

          {showSuggestions && query.trim().length > 0 && suggestions.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-card border border-border rounded-xl shadow-lg py-1.5 z-20 max-h-[260px] overflow-y-auto">
              {suggestions.map((s: string, i: number) => (
                <button
                  key={s + i}
                  onMouseDown={() => { runAnalysis(s); setShowSuggestions(false); }}
                  onMouseEnter={() => setActiveIndex(i)}
                  className={`w-full flex items-center gap-3 px-4 py-2.5 text-sm text-foreground hover:bg-secondary transition-colors text-left ${i === activeIndex ? "bg-secondary" : ""}`}
                >
                  <Search size={13} className="text-primary flex-shrink-0" />
                  <span className="truncate">{s}</span>
                </button>
              ))}
            </div>
          )}
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

      {/* Processing — 4 stages driven by the real request lifecycle
          (App: ask sent → goal payload → analytics payload → reveal).
          Chart skeleton reserves layout; reveal swaps it in, then static. */}
      {state === "processing" && (
        <div className="space-y-4">
          <AIProcessingIndicator stage={aiStage} />
          <div className="bg-card border border-border rounded-xl p-5 space-y-3" aria-hidden="true">
            <div className="chart-skeleton h-5 w-48" />
            <div className="chart-skeleton h-[220px] w-full" />
            <div className="flex gap-2">
              <div className="chart-skeleton h-8 w-24" />
              <div className="chart-skeleton h-8 w-24" />
            </div>
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
            {(followUps.length > 0 ? followUps : getDynamicSuggestions(goalResult)).slice(0, 4).map((q) => (
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
          {/* Graceful states: actionable copy, never stack traces/SQL/raw errors */}
          {resultStatus && resultStatus !== "success" && (
            <div className="bg-warning/10 border border-warning/30 rounded-xl p-4 flex items-start gap-3">
              <AlertCircle size={15} className="text-warning mt-0.5 flex-shrink-0" />
              <div>
                <p className="text-sm font-medium text-foreground capitalize">{resultStatus.replace(/-/g, " ")}</p>
                <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                  {resultMessage || "Try narrowing to one metric or period and ask again."}
                </p>
              </div>
            </div>
          )}

          {/* Answer */}
          {answer && (
            <div className="premium-card bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                  <Sparkles size={12} className="text-primary" />
                </div>
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Answer</p>
                {interpreted?.primary && (
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded capitalize">
                    {String(interpreted.primary).replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <p className="text-[14px] font-medium text-foreground leading-relaxed">
                {answer}
              </p>
              {comparisonPeriod?.description && (
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                  {comparisonPeriod.description}
                </p>
              )}
              {findings.length > 1 && (
                <ul className="space-y-1.5 pt-1">
                  {findings.slice(0, 5).map((f: any, i: number) => (
                    <li key={i} className="text-[13px] text-foreground leading-relaxed flex gap-2">
                      <span className="text-primary mt-0.5">·</span>
                      <span>{typeof f === "string" ? f : JSON.stringify(f)}</span>
                    </li>
                  ))}
                </ul>
              )}
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
              {/* Server-defined KPIs (t.txt-5): rendered as-is, never recomputed */}
              {goalResult?.display?.kpis && Object.keys(goalResult.display.kpis).length > 0 && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {Object.entries(goalResult.display.kpis).slice(0, 3).map(([k, v]: any) => {
                    const sum = Number(v?.sum);
                    const avg = Number(v?.avg);
                    return (
                      <span key={k} className="text-[11px] px-2 py-1 rounded-md bg-secondary border border-border text-muted-foreground">
                        {k}: <span className="text-foreground font-semibold">{isNaN(sum) ? "—" : sum.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
                        <span className="ml-1">avg {isNaN(avg) ? "—" : avg.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
                      </span>
                    );
                  })}
                </div>
              )}
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

          {/* Possible drivers — embedded hypothesis capability (evidence-backed) */}
          {(possibleDrivers.length > 0 || hypothesisObj) && (
            <div className="bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <TrendingUp size={14} className="text-primary" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Possible drivers</p>
                {hypothesisObj?.confidence && (
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                    {hypothesisObj.confidence} confidence
                  </span>
                )}
              </div>
              {hypothesisObj?.text && (
                <p className="text-sm text-foreground leading-relaxed">{hypothesisObj.text}</p>
              )}
              {possibleDrivers.length > 0 && (
                <div className="space-y-2">
                  {possibleDrivers.slice(0, 5).map((d: any, i: number) => (
                    <div key={i} className="flex items-center gap-3 bg-secondary/40 rounded-lg px-3 py-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-[13px] font-medium text-foreground truncate">{d.driver || d.value}</p>
                        <p className="text-[11px] text-muted-foreground">
                          {d.metric}{d.period ? ` · ${d.period}` : ""}{d.confidence ? ` · ${d.confidence} confidence` : ""}
                          {d.evidence?.table ? ` · ${d.evidence.table}` : ""}
                        </p>
                      </div>
                      {d.contribution_pct !== undefined && (
                        <span className="text-[13px] font-semibold text-primary flex-shrink-0">
                          {d.contribution_pct}%
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Recommendations (from the result, never invented) */}
          {recommendationsList.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5 space-y-2">
              <div className="flex items-center gap-2">
                <Lightbulb size={14} className="text-primary" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Recommendations</p>
              </div>
              <ul className="space-y-1.5">
                {recommendationsList.slice(0, 4).map((r: any, i: number) => (
                  <li key={i} className="text-[13px] text-foreground leading-relaxed flex gap-2">
                    <span className="text-primary mt-0.5">·</span>
                    <span>
                      {typeof r === "string" ? r : (r.text || JSON.stringify(r))}
                      {r?.confidence && <span className="text-muted-foreground"> ({r.confidence} confidence)</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Limitations (honest, from the backend) */}
          {limitations.length > 0 && (
            <div className="bg-secondary/40 border border-border rounded-xl p-4 space-y-1">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Limitations</p>
              {limitations.slice(0, 4).map((lim: any, i: number) => (
                <p key={i} className="text-xs text-muted-foreground leading-relaxed">· {typeof lim === "string" ? lim : JSON.stringify(lim)}</p>
              ))}
            </div>
          )}

          {/* Visualization: skeleton swapped for a one-shot reveal (keyed by
              question so each new analysis replays it once, then static).
              Click a mark to drill down — Investigate / Explain / Forecast
              hooks travel with the shared context. */}
          {chartRenderData.length > 0 && xKey && yKey && (
            <div className="bg-card border border-border rounded-xl p-5 chart-reveal" key={submittedQ || query}>
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
                    <Tooltip content={<BizTooltip />} />
                    <Area type="monotone" dataKey={yKey} stroke={CHART_COLORS[0]} fill={CHART_COLORS[0]} fillOpacity={0.15} strokeWidth={2} />
                  </AreaChart>
                ) : chartType === "scatter" ? (
                  <ScatterChart>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                    <XAxis dataKey={xKey} name={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis dataKey={yKey} name={yKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      content={<BizTooltip />}
                      cursor={{ strokeDasharray: "3 3" }}
                    />
                    <Scatter data={chartRenderData} fill={CHART_COLORS[0]} fillOpacity={0.6} />
                  </ScatterChart>
                ) : chartType === "hbar" ? (
                  <BarChart data={chartRenderData} layout="vertical" barSize={22}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} horizontal={false} />
                    <XAxis type="number" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis type="category" dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={110} />
                    <Tooltip content={<BizTooltip />} />
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
                    <Tooltip content={<BizTooltip />} />
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
                      label={({ name, percent }) => `${name} ${((percent ?? 0) * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {chartRenderData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip content={<BizTooltip />} />
                  </PieChart>
                ) : (
                  <BarChart data={chartRenderData} barSize={36} onClick={onChartClick}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip content={<BizTooltip />} />
                    <Bar dataKey={yKey} radius={[5, 5, 0, 0]}>
                      {chartRenderData.map((row: any, i: number) => (
                        <Cell
                          key={i}
                          fill={chartType === "histogram" ? CHART_COLORS[0] : colorForName(String(row?.[xKey] ?? i))}
                          fillOpacity={chartType === "histogram" ? 0.55 + (0.45 * i) / Math.max(1, chartRenderData.length) : 1}
                        />
                      ))}
                    </Bar>
                  </BarChart>
                )}
              </ResponsiveContainer>
              {drill && (
                <div className="mt-3 rounded-lg border border-primary/25 bg-primary/5 px-3 py-2.5">
                  <p className="text-xs text-foreground">
                    <span className="font-semibold">{drill.label}</span>
                    {drill.value !== null && drill.value !== undefined && (
                      <span className="text-muted-foreground"> · {typeof drill.value === "number" ? drill.value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(drill.value)}</span>
                    )}
                    <span className="text-muted-foreground"> — what next?</span>
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <button
                      onClick={() => {
                        drillHooks(drill.label);
                        const wq = `Why did ${yKey || "the metric"} change for ${drill.label}?`;
                        setQuery(wq);
                        onAsk?.(wq);
                        setDrill(null);
                      }}
                      className="text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
                    >
                      Investigate why
                    </button>
                    <button
                      onClick={() => {
                        drillHooks(drill.label);
                        onAsk?.(`Explain this finding: ${drill.label} in ${query || submittedQ}`);
                      }}
                      className="text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
                    >
                      Explain
                    </button>
                    <button
                      onClick={() => {
                        drillHooks(drill.label);
                        gotoWithContext("predictive", { metric: yKey });
                      }}
                      className="text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
                    >
                      Forecast
                    </button>
                    <button
                      onClick={() => setDrill(null)}
                      className="text-[11px] text-muted-foreground hover:text-foreground px-2 py-1.5"
                    >
                      Clear
                    </button>
                  </div>
                </div>
              )}
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

          {/* Evidence — tables/columns/values only. Raw SQL stays backend-only
              and is never rendered on this user-facing page. */}
          {evidenceList.length > 0 && (
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <button
                onClick={() => setShowEvidence((e) => !e)}
                className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-secondary/40 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Database size={14} className="text-muted-foreground" />
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Evidence</p>
                  {evidenceList[0]?.tables?.length > 0 && (
                    <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                      {evidenceList[0].tables.slice(0, 3).join(", ")}
                    </span>
                  )}
                </div>
                {showEvidence ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
              </button>
              {showEvidence && (
                <div className="border-t border-border px-5 py-4 space-y-2 text-xs text-muted-foreground leading-relaxed">
                  <p>Tables: {(evidenceList[0]?.tables || []).join(", ") || "—"}</p>
                  <p>Columns: {(evidenceList[0]?.columns || []).join(", ") || "—"}</p>
                  <p>Rows analyzed: {evidenceList[0]?.row_count ?? tableData.length}</p>
                </div>
              )}
            </div>
          )}

          {/* P2 §20: raw SQL / raw JSON / chain-of-thought / prompts are never
              exposed on this user-facing page. Provenance (source/tables/
              columns/SQL trace) stays in the backend goalResult payload for
              admin/debug use only. */}

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

          {/* Next actions: handoffs carry the shared analysis context
              (localStorage aria_analysis_context + hash params) so the user
              never retypes and the target page never re-analyzes. */}
          <div className="space-y-2">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Next actions</p>
            <div className="flex flex-wrap gap-2">
              <button
                onClick={() => {
                  const m = analysisMeta?.entity || yKey || "the metric";
                  const wq = `Why did ${m} change?`;
                  setQuery(wq);
                  runAnalysis(wq);
                }}
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
              >
                Investigate why
              </button>
              <button
                onClick={() => {
                  const q = `Compare this period with the previous period for: ${query || submittedQ || "the current analysis"}`;
                  setQuery(q);
                  runAnalysis(q);
                }}
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
              >
                Compare periods
              </button>
              <button
                onClick={() => {
                  const m = analysisMeta?.entity || yKey || "";
                  const period = comparisonPeriod?.granularity || (goalResult?.comparison_period as any)?.granularity || "";
                  const table = (goalResult?.relevantTables || [])[0] || null;
                  const q = query || submittedQ || "";
                  saveAnalysisContext({
                    origin: "analytics",
                    question: q || null,
                    metric: m || null,
                    dimension: xKey || null,
                    table,
                    period: period || null,
                    dateRange: period || null,
                  });
                  try {
                    localStorage.setItem("aria_forecast_context", JSON.stringify({
                      metric: m || undefined,
                      dataset: table || undefined,
                      date: period || undefined,
                      granularity: period || undefined,
                      question: q || undefined,
                    }));
                  } catch { /* best-effort */ }
                  gotoWithContext("predictive", { metric: m, period: period || undefined, question: q || undefined });
                }}
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
              >
                Forecast
              </button>
              <button
                onClick={goRelatedInsights}
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
              >
                Related insights
              </button>
              <button
                onClick={goCopilotAnalysis}
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
              >
                Continue in Copilot
              </button>
              <button
                onClick={goHistory}
                className="text-xs font-medium px-3 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors"
              >
                Save analysis
              </button>
            </div>
          </div>

          {/* n.txt-10: Source & Provenance removed from this user-facing page.
              Provenance (source/tables/columns/SQL trace) stays in the backend
              goalResult payload for admin/debug use only. */}
        </div>
      )}
    </div>
  );
}
