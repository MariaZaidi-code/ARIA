import { useState, useEffect, useRef, useCallback } from "react";
import { ArrowRight, ArrowUpRight, ArrowDownRight, Zap, Search, AlertTriangle, ChevronRight, RefreshCw } from "lucide-react";
import { AreaChart, Area, BarChart, Bar, Cell, ResponsiveContainer, Tooltip, CartesianGrid, XAxis, YAxis } from "recharts";
import { useTheme } from "../App";
import type { Page } from "../App";
import { colorForName } from "../lib/charts";

interface DashboardProps {
  setPage: (p: Page) => void;
  onAsk?: (question: string) => void;
  user?: { email?: string } | null;
  connectionStatus?: string;
  dbName?: string;
  insightResult?: any;
  analysisResult?: any;
  connectionError?: string;
}

// Fallback suggestions when the backend has none yet (domain-neutral).
const fallbackExamples = [
  "What are the totals of the main measures?",
  "Which segments appear most frequently?",
  "Show the trend over time",
  "Find unusual changes in the data",
];

const typeColor: Record<string, string> = {
  Growth: "text-positive bg-positive/10",
  Anomaly: "text-negative bg-negative/10",
  Opportunity: "text-warning bg-warning/10",
  Risk: "text-negative bg-negative/10",
  Trend: "text-primary bg-primary/10",
};

const severityDot: Record<string, string> = {
  high: "bg-negative",
  medium: "bg-warning",
  low: "bg-positive",
};

const fmt = (n: number, prefix = "") =>
  n >= 1_000_000
    ? `${prefix}${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000
    ? `${prefix}${(n / 1_000).toFixed(1)}K`
    : `${prefix}${Number(n).toLocaleString()}`;

function MetricCard({ kpi }: { kpi: any }) {
  const rawValue = typeof kpi.rawValue === "number"
    ? kpi.rawValue
    : parseFloat(String(kpi.value).replace(/[^0-9eE.+-]/g, "")) || 0;
  const change = Number(kpi.change) || 0;
  const positive = change >= 0;
  const prefix = kpi.format === "currency" ? "$" : "";
  // Real sparkline only: backend-provided points, otherwise no sparkline (never fake).
  const spark = Array.isArray(kpi.spark) && kpi.spark.length > 1
    ? kpi.spark.map((v: any) => ({ v: Number(v) || 0 }))
    : Array.isArray(kpi.trend) && kpi.trend.length > 1
      ? kpi.trend.map((v: any) => ({ v: Number(v?.value ?? v) || 0 }))
      : [];
  return (
    <div className="bg-card border border-border rounded-xl p-5 flex flex-col gap-3 hover:shadow-sm transition-shadow">
      <div className="flex items-center justify-between">
        <p className="text-xs font-medium text-muted-foreground">{kpi.label}</p>
        {change !== 0 && kpi.format !== "text" && (
          <span className={`flex items-center gap-0.5 text-xs font-medium ${positive ? "text-positive" : "text-negative"}`}>
            {positive ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
            {Math.abs(change)}%
          </span>
        )}
      </div>
      <p className="text-2xl font-semibold text-foreground tracking-tight">
        {kpi.format === "text" ? String(kpi.value) : fmt(rawValue, prefix)}
      </p>
      {spark.length > 0 && (
        <div className="h-10">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={spark}>
              <defs>
                <linearGradient id={`grad-${kpi.id || kpi.label}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={positive ? "var(--positive)" : "var(--negative)"} stopOpacity={0.2} />
                  <stop offset="95%" stopColor={positive ? "var(--positive)" : "var(--negative)"} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area
                type="monotone" dataKey="v"
                stroke={positive ? "var(--positive)" : "var(--negative)"}
                strokeWidth={1.5} fill={`url(#grad-${kpi.id || kpi.label})`} dot={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-xs text-muted-foreground">{kpi.period || "All time"}</p>
    </div>
  );
}

export default function Dashboard({ setPage, onAsk, user, connectionStatus = "not-connected", dbName = "", insightResult = null, analysisResult = null, connectionError = "" }: DashboardProps) {
  const { isDark } = useTheme();
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<any>(null);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  const trackSuggestionClick = async (text: string) => {
    try {
      const token = localStorage.getItem("aria_auth_token");
      if (token) {
        await fetch("/api/feedback/suggestion", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ suggestion_text: text, source: "dashboard" }),
        });
      }
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };

  const fetchConfig = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("aria_auth_token") || "";
      const res = await fetch("/api/dashboard/config", {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.ok) {
        setConfig(data.config);
        setLastUpdated(Date.now());
      } else {
        setError(data?.error || "Failed to load dashboard.");
      }
    } catch (e: any) {
      setError(e?.message || "Network error.");
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchAutocomplete = useCallback(async (partial: string) => {
    const token = localStorage.getItem("aria_auth_token") || "";
    try {
      const res = await fetch(`/api/autocomplete?partial=${encodeURIComponent(partial)}&limit=6`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) { setSuggestions([]); return; }
      const data = await res.json();
      const list = Array.isArray(data?.suggestions)
        ? data.suggestions.map((s: any) => typeof s === "string" ? s : s.text)
        : [];
      setSuggestions(list);
    } catch {
      setSuggestions([]);
    }
  }, []);

  useEffect(() => {
    if (connectionStatus === "connected") {
      fetchConfig();
      fetchAutocomplete("");
    }
  }, [connectionStatus, fetchConfig, fetchAutocomplete]);

  useEffect(() => {
    if (connectionStatus !== "connected") return;
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchAutocomplete(query || ""), 250);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query, connectionStatus, fetchAutocomplete]);

  const handleSubmit = () => {
    const q = query.trim();
    if (q) { onAsk?.(q); setPage("analytics"); }
  };

  const askExample = (q: string) => {
    trackSuggestionClick(q);
    setQuery(q);
    onAsk?.(q);
    setPage("analytics");
  };

  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-20">
          <div className="w-16 h-16 rounded-2xl mx-auto mb-5 flex items-center justify-center" style={{ background: "var(--gradient-primary)" }}>
            <Search size={24} className="text-white" />
          </div>
          <h2 className="text-2xl font-semibold text-foreground tracking-tight mb-2">
            {connectionStatus === "failed" ? "Connection Failed" : "Connect a Data Source"}
          </h2>
          <p className="text-sm text-muted-foreground mb-4 max-w-sm mx-auto">
            {connectionStatus === "failed" && connectionError ? connectionError : "Get started by connecting your database to unlock AI-powered insights."}
          </p>
          <button onClick={() => setPage("data")} className="px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all" style={{ background: "var(--gradient-primary)" }}>
            Connect Now
          </button>
        </div>
      </div>
    );
  }

  const metrics: any[] = config?.metrics || [];
  const charts: any[] = config?.visualizations || [];
  const recommendations: any[] = config?.recommendations || [];
  const summary = config?.summary || {};
  const rawInsights: any[] = insightResult?.keyInsights || insightResult?.insights || [];
  const anomalies: any[] = insightResult?.anomalies || analysisResult?.anomalies || [];
  const exampleQuestions = recommendations.length > 0
    ? recommendations.slice(0, 4).map((r: any) => typeof r === "string" ? r : r.question)
    : fallbackExamples;
  const recommendedCards = recommendations.length > 0
    ? recommendations.slice(0, 4).map((r: any, i: number) => ({
        q: typeof r === "string" ? r : r.question,
        tag: (typeof r === "object" && r.tag) || ["Analysis", "Trend", "Forecast", "Segments"][i % 4],
      }))
    : fallbackExamples.map((q, i) => ({ q, tag: ["Analysis", "Trend", "Segments", "Overview"][i % 4] }));

  const hour = new Date().getHours();
  const greeting = `Good ${hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening"}, ${user?.email?.split("@")[0] || "there"}`;

  const areaChart = charts.find((c: any) => ["area", "line"].includes(c.type)) || charts[0];
  const barChart = charts.find((c: any) => c.type === "bar" && c !== areaChart) || charts[1];

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-8">
      {/* Greeting + Query */}
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-semibold text-foreground tracking-tight">{greeting}</h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              {summary.title || (dbName ? `Here's what ARIA found in ${dbName}.` : "Here's what ARIA found in your business data.")}
            </p>
            {summary.totalRows > 0 && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {summary.tableCount} tables, {summary.totalRows.toLocaleString()} records
              </p>
            )}
          </div>
          <div className="flex items-center gap-2">
            {lastUpdated && <span className="text-[11px] text-muted-foreground">Updated {new Date(lastUpdated).toLocaleTimeString()}</span>}
            <button onClick={fetchConfig} disabled={loading}
              className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-secondary hover:bg-secondary/70 text-foreground transition-colors border border-border disabled:opacity-50">
              <RefreshCw size={12} className={loading ? "animate-spin" : ""} /> Refresh
            </button>
          </div>
        </div>

        <div className="relative">
          <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3.5 focus-within:border-primary transition-colors shadow-sm">
            <Search size={16} className="text-muted-foreground flex-shrink-0" />
            <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder="Ask ARIA anything about your business..."
              className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none" />
            <button onClick={handleSubmit}
              className="flex-shrink-0 bg-primary text-primary-foreground px-3 py-1.5 rounded-lg text-xs font-medium hover:opacity-90 transition-opacity">
              Ask
            </button>
          </div>

          {showSuggestions && (query.length > 0 ? suggestions.length > 0 : exampleQuestions.length > 0) && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-card border border-border rounded-xl shadow-lg py-1.5 z-20 max-h-[260px] overflow-y-auto">
              {(query.length > 0 ? suggestions : exampleQuestions).map((s: string, i: number) => (
                <button key={s + i} onMouseDown={() => askExample(s)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-foreground hover:bg-secondary transition-colors text-left">
                  <Zap size={13} className="text-primary flex-shrink-0" />
                  <span className="truncate">{s}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {exampleQuestions.map((ex) => (
            <button key={ex} onClick={() => askExample(ex)}
              className="text-xs px-3 py-1.5 rounded-full bg-secondary hover:bg-secondary/80 text-muted-foreground hover:text-foreground transition-colors border border-border">
              {ex}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="bg-negative/10 border border-negative/30 text-negative text-sm rounded-xl px-4 py-2">{error}</div>}

      {/* KPI Cards */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Business Overview</h3>
        {loading && metrics.length === 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="bg-card border border-border rounded-xl p-5 animate-pulse">
                <div className="h-3 bg-secondary rounded w-16 mb-3" />
                <div className="h-7 bg-secondary rounded w-24 mb-2" />
                <div className="h-10 bg-secondary rounded w-full" />
              </div>
            ))}
          </div>
        ) : metrics.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {metrics.slice(0, 5).map((kpi: any) => (
              <MetricCard key={kpi.id || kpi.label} kpi={kpi} />
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">KPIs will appear once your data is analyzed.</div>
        )}
      </section>

      {/* AI Highlights */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">ARIA Intelligence</h3>
          <button onClick={() => setPage("insights")} className="text-xs text-primary hover:underline flex items-center gap-1">
            View all <ChevronRight size={12} />
          </button>
        </div>
        {rawInsights.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {rawInsights.slice(0, 4).map((ins: any, i: number) => (
              <div key={ins.id || i} className="bg-card border border-border rounded-xl p-4 hover:shadow-sm transition-shadow flex gap-4">
                <div className={`mt-0.5 w-2 h-2 rounded-full flex-shrink-0 ${severityDot[ins.severity] || "bg-primary"}`} />
                <div className="flex-1 min-w-0 space-y-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-foreground leading-snug">{ins.title || "Insight"}</p>
                    {(ins.type || ins.category) && (
                      <span className={`flex-shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${typeColor[ins.type] || typeColor[ins.category] || "text-muted-foreground bg-secondary"}`}>
                        {ins.type || ins.category}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{ins.description || ins.explanation || ""}</p>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-xs text-muted-foreground">
                      {ins.magnitude && <span className="font-semibold text-foreground">{ins.magnitude}</span>}
                      {ins.confidence && <span>{ins.confidence}{String(ins.confidence).includes("%") ? "" : "%"} confidence</span>}
                    </div>
                    <button onClick={() => setPage("insights")} className="text-xs text-primary hover:underline flex items-center gap-0.5">
                      Explore <ArrowRight size={11} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">Insights will appear after analysis.</div>
        )}
      </section>

      {/* Charts */}
      {(areaChart || barChart) && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Analytics Overview</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {areaChart && (
              <div className="bg-card border border-border rounded-xl p-5">
                <div className="flex items-center justify-between mb-5">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{areaChart.title || "Trend"}</p>
                    {areaChart.subtitle && <p className="text-xs text-muted-foreground mt-0.5">{areaChart.subtitle}</p>}
                  </div>
                </div>
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={areaChart.data || []}>
                    <defs>
                      <linearGradient id="dashAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.2} />
                        <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={areaChart.xKey || "period"} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={48} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                      itemStyle={{ color: "var(--muted-foreground)" }}
                    />
                    <Area type="monotone" dataKey={areaChart.dataKey || "value"} stroke="var(--primary)" strokeWidth={2} fill="url(#dashAreaGrad)" dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            {barChart && (
              <div className="bg-card border border-border rounded-xl p-5">
                <div className="flex items-center justify-between mb-5">
                  <div>
                    <p className="text-sm font-semibold text-foreground">{barChart.title || "Breakdown"}</p>
                    {barChart.subtitle && <p className="text-xs text-muted-foreground mt-0.5">{barChart.subtitle}</p>}
                  </div>
                </div>
                <ResponsiveContainer width="100%" height={180}>
                  <BarChart data={barChart.data || []} barSize={28}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={barChart.xKey || "name"} tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                      itemStyle={{ color: "var(--muted-foreground)" }}
                    />
                    <Bar dataKey={barChart.dataKey || "value"} radius={[4, 4, 0, 0]}>
                      {(barChart.data || []).map((entry: any, i: number) => (
                        <Cell key={i} fill={entry?.fill || colorForName(String(entry?.[barChart.xKey || "name"] ?? i))} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </section>
      )}

      {/* Anomalies */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
          <AlertTriangle size={12} /> Detected Anomalies
        </h3>
        {anomalies.length > 0 ? (
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border">
                  <th className="text-left text-xs font-medium text-muted-foreground px-5 py-3">Metric</th>
                  <th className="text-left text-xs font-medium text-muted-foreground px-5 py-3">Date</th>
                  <th className="text-left text-xs font-medium text-muted-foreground px-5 py-3">Deviation</th>
                  <th className="text-left text-xs font-medium text-muted-foreground px-5 py-3 hidden md:table-cell">Explanation</th>
                  <th className="text-left text-xs font-medium text-muted-foreground px-5 py-3">Severity</th>
                </tr>
              </thead>
              <tbody>
                {anomalies.map((a: any, i: number) => (
                  <tr key={a.id || i} className={`${i < anomalies.length - 1 ? "border-b border-border" : ""} hover:bg-secondary/40 transition-colors`}>
                    <td className="px-5 py-3 font-medium text-foreground text-sm">{a.metric || a.column || "—"}</td>
                    <td className="px-5 py-3 text-muted-foreground text-sm">{a.date || a.detected || "—"}</td>
                    <td className="px-5 py-3">
                      <span className="text-sm font-semibold text-foreground">{a.deviation || a.magnitude || `${a.z_score ?? ""}`}</span>
                    </td>
                    <td className="px-5 py-3 text-muted-foreground text-xs leading-relaxed hidden md:table-cell max-w-xs truncate">{a.explanation || a.description || ""}</td>
                    <td className="px-5 py-3">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full capitalize
                        ${a.severity === "high" ? "text-negative bg-negative/10" : a.severity === "medium" ? "text-warning bg-warning/10" : "text-positive bg-positive/10"}`}>
                        {a.severity || "low"}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-5 text-center text-muted-foreground text-sm">No anomalies detected in the current data.</div>
        )}
      </section>

      {/* Recommended Questions */}
      <section className="space-y-3 pb-4">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Recommended Questions</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {recommendedCards.map(({ q, tag }) => (
            <button key={q}
              onClick={() => askExample(q)}
              className="flex items-center justify-between bg-card border border-border rounded-xl px-4 py-3.5 hover:border-primary/40 hover:shadow-sm transition-all text-left group">
              <div className="space-y-1">
                <p className="text-sm text-foreground group-hover:text-primary transition-colors">{q}</p>
                <span className="text-xs text-muted-foreground bg-secondary px-2 py-0.5 rounded-full">{tag}</span>
              </div>
              <ArrowRight size={14} className="text-muted-foreground group-hover:text-primary transition-colors ml-3 flex-shrink-0" />
            </button>
          ))}
        </div>
      </section>

      {/* Data Quality */}
      {config?.quality && Object.keys(config.quality).length > 0 && (
        <section className="space-y-3 pb-4">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Data Quality</h3>
          <div className="bg-card border border-border rounded-xl p-5 text-sm text-muted-foreground">
            {Object.entries(config.quality).slice(0, 6).map(([k, v]: [string, any]) => (
              <div key={k} className="flex items-center justify-between py-1.5 border-b border-border last:border-0">
                <span className="capitalize">{k.replace(/_/g, " ")}</span>
                <span className="font-semibold text-foreground">{typeof v === "number" ? v.toLocaleString() : String(v)}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
