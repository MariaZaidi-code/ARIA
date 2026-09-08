import { useState, useEffect, useCallback, useRef } from "react";
import { ArrowUpRight, ArrowDownRight, Zap, Search, AlertTriangle, ChevronRight, RefreshCw, TrendingUp, TrendingDown, Users, ShoppingCart, Package, DollarSign, Award, BarChart3, Brain, Lightbulb, LineChart, Pill, FlaskConical, Database } from "lucide-react";
import { AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell, ResponsiveContainer, Tooltip, CartesianGrid, XAxis, YAxis } from "recharts";
import { useTheme } from "../App";
import type { Page } from "../App";

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

const ICON_MAP: Record<string, any> = {
  database: Database, dollar: DollarSign, users: Users, "shopping-cart": ShoppingCart,
  package: Package, "trending-up": TrendingUp, award: Award, "bar-chart": BarChart3,
};

const SECTION_ICONS: Record<string, any> = {
  analytics: Brain, insights: Lightbulb, predictive: LineChart, prescription: Pill, hypothesis: FlaskConical,
};

const SECTION_PAGES: Record<string, Page> = {
  analytics: "analytics", insights: "insights", predictive: "predictive",
  prescription: "prescription", hypothesis: "hypothesis",
};

const SECTION_COLORS: Record<string, string> = {
  analytics: "#4F46E5", insights: "#059669", predictive: "#F59E0B",
  prescription: "#EC4899", hypothesis: "#8B5CF6",
};

function AnimatedKPICard({ kpi, index }: { kpi: any; index: number }) {
  const [mounted, setMounted] = useState(false);
  const [sparkData, setSparkData] = useState<{ v: number }[]>([]);
  const Icon = ICON_MAP[kpi.icon] || TrendingUp;
  const positive = (kpi.change || 0) >= 0;
  const color = kpi.color || "#4F46E5";
  const rawValue = typeof kpi.rawValue === "number" ? kpi.rawValue : parseFloat(String(kpi.value).replace(/[^0-9eE.+-]/g, "")) || 0;

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), index * 80);
    return () => clearTimeout(t);
  }, [index]);

  useEffect(() => {
    if (!mounted) return;
    const base = rawValue;
    const points = 20;
    const data: { v: number }[] = [];
    for (let i = 0; i < points; i++) {
      const progress = i / (points - 1);
      const trend = positive ? 1 + progress * 0.3 : 1 - progress * 0.2;
      const noise = 1 + (Math.sin(i * 1.7 + index) * 0.08);
      data.push({ v: base * trend * noise * (0.85 + Math.random() * 0.15) });
    }
    setSparkData(data);
  }, [mounted, rawValue, positive, index]);

  const formatValue = (v: number) => {
    if (kpi.format === "currency") {
      if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(2)}M`;
      if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
      return `$${v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
    }
    if (kpi.format === "text") return String(kpi.value);
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
    return v.toLocaleString();
  };

  return (
    <div
      className={`premium-card bg-card border border-border rounded-xl p-4 flex flex-col gap-2 cursor-default overflow-hidden relative transition-all duration-500 ${mounted ? "opacity-100 translate-y-0" : "opacity-0 translate-y-3"}`}
      style={{ transitionDelay: `${index * 80}ms` }}
    >
      {sparkData.length > 0 && (
        <div className="absolute inset-0 opacity-[0.06] pointer-events-none">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sparkData}>
              <defs>
                <linearGradient id={`spark-bg-${index}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={color} stopOpacity={1} />
                  <stop offset="100%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="v" stroke="none" fill={`url(#spark-bg-${index})`} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <div className="flex items-center justify-between relative z-10">
        <div className="flex items-center gap-1.5">
          <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ background: `${color}18` }}>
            <Icon size={12} style={{ color }} />
          </div>
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">{kpi.label}</p>
        </div>
        {kpi.change !== 0 && kpi.format !== "text" && (
          <span className={`flex items-center gap-0.5 text-[11px] font-semibold px-1.5 py-0.5 rounded-full ${positive ? "text-positive bg-positive/10" : "text-negative bg-negative/10"}`}>
            {positive ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
            {Math.abs(kpi.change)}%
          </span>
        )}
      </div>
      <p className="text-[22px] font-bold text-foreground tracking-tight relative z-10">
        {kpi.format === "text" ? kpi.value : formatValue(rawValue)}
      </p>
      {sparkData.length > 0 && (
        <div className="h-8 -mx-1 relative z-10">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={sparkData}>
              <defs>
                <linearGradient id={`spark-${index}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={color} stopOpacity={0.25} />
                  <stop offset="95%" stopColor={color} stopOpacity={0} />
                </linearGradient>
              </defs>
              <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} fill={`url(#spark-${index})`} dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
      <p className="text-[10px] text-muted-foreground relative z-10">{kpi.period || "All time"}</p>
    </div>
  );
}

function SectionCard({ section, setPage }: { section: any; setPage: (p: Page) => void }) {
  const [mounted, setMounted] = useState(false);
  const Icon = SECTION_ICONS[section.type] || Brain;
  const color = SECTION_COLORS[section.type] || "#4F46E5";

  useEffect(() => {
    const t = setTimeout(() => setMounted(true), 100);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className={`premium-card bg-card border border-border rounded-xl p-4 flex flex-col gap-3 transition-all duration-500 ${mounted ? "opacity-100 translate-y-0" : "opacity-0 translate-y-3"}`}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: `${color}15` }}>
            <Icon size={14} style={{ color }} />
          </div>
          <p className="text-sm font-semibold text-foreground">{section.title}</p>
        </div>
        {section.metric && (
          <span className="text-xs font-bold px-2 py-0.5 rounded-full" style={{ color, background: `${color}12` }}>
            {section.metric}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{section.description}</p>
      <button
        onClick={() => setPage(SECTION_PAGES[section.type] || "analytics")}
        className="self-start text-xs font-semibold px-3 py-1.5 rounded-lg transition-all hover:opacity-80"
        style={{ color, background: `${color}12`, border: `1px solid ${color}25` }}
      >
        Thorough Analysis
      </button>
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

  // Track suggestion clicks for personalization (Section 62)
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
    } catch {}
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

  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-20 animate-fade-in">
          <div className="w-16 h-16 rounded-2xl mx-auto mb-5 flex items-center justify-center" style={{ background: "var(--gradient-primary)" }}>
            <Search size={24} className="text-white" />
          </div>
          <h2 className="text-2xl font-bold text-foreground mb-2">
            {connectionStatus === "failed" ? "Connection Failed" : "Connect a Data Source"}
          </h2>
          <p className="text-sm text-muted-foreground mb-4 max-w-sm mx-auto">
            {connectionStatus === "failed" && connectionError ? connectionError : "Get started by connecting your database to unlock AI-powered insights."}
          </p>
          <button onClick={() => setPage("data")} className="premium-btn btn-glow px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all" style={{ background: "var(--gradient-primary)" }}>
            Connect Now
          </button>
        </div>
      </div>
    );
  }

  const metrics = config?.metrics || [];
  const charts = config?.visualizations || [];
  const sections = config?.sections || [];
  const recommendations = config?.recommendations || [];
  const summary = config?.summary || {};
  const quality = config?.quality || {};
  const insights = insightResult?.keyInsights || insightResult?.insights || [];

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-8">
      {/* Greeting + Search */}
      <div className="space-y-4 animate-fade-in">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold text-foreground tracking-tight">
              Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 18 ? "afternoon" : "evening"}, {user?.email?.split("@")[0] || "User"}
            </h2>
            <p className="text-sm text-muted-foreground mt-1">
              {summary.title || (dbName ? `Here's what ARIA found in ${dbName}.` : "Here's what ARIA found in your data.")}
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

        {/* Search bar */}
        <div className="relative">
          <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3 focus-within:border-primary/50 focus-within:shadow-[0_0_0_3px_var(--primary-light)] transition-all duration-200" style={{ boxShadow: "var(--shadow-sm)" }}>
            <Search size={16} className="text-muted-foreground flex-shrink-0" />
            <input ref={inputRef} value={query} onChange={(e) => setQuery(e.target.value)}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 200)}
              onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder="Ask ARIA anything about your data..."
              className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none" />
            <button onClick={handleSubmit}
              className="premium-btn btn-glow flex-shrink-0 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all"
              style={{ background: "var(--gradient-primary)" }}>
              Ask
            </button>
          </div>
          {showSuggestions && (query.length > 0 ? suggestions.length > 0 : recommendations.length > 0) && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-card border border-border rounded-xl shadow-lg py-1 z-20 max-h-[260px] overflow-y-auto">
              {(query.length > 0 ? suggestions : recommendations.map((r: any) => r.question)).map((s: string, i: number) => (
                <button key={s + i} onMouseDown={() => { trackSuggestionClick(s); setQuery(s); onAsk?.(s); setPage("analytics"); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-foreground hover:bg-secondary transition-colors text-left">
                  <Zap size={13} className="text-primary flex-shrink-0" />
                  <span className="truncate">{s}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Recommendations from backend */}
        {recommendations.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {recommendations.slice(0, 6).map((r: any, i: number) => (
              <button key={r.id || i} onClick={() => { setQuery(r.question); onAsk?.(r.question); setPage("analytics"); }}
                className="text-xs px-3 py-1.5 rounded-full bg-secondary hover:bg-secondary/70 text-muted-foreground hover:text-foreground transition-colors border border-border">
                {r.question}
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className="bg-negative/10 border border-negative/30 text-negative text-sm rounded-xl px-4 py-2">{error}</div>}

      {/* KPI Cards — backend-driven, no hardcoded logic */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Key Metrics</h3>
        {loading && metrics.length === 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="bg-card border border-border rounded-xl p-4 animate-pulse">
                <div className="h-3 bg-secondary rounded w-16 mb-3" />
                <div className="h-6 bg-secondary rounded w-24 mb-2" />
                <div className="h-8 bg-secondary rounded w-full" />
              </div>
            ))}
          </div>
        ) : metrics.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {metrics.slice(0, 5).map((kpi: any, i: number) => (
              <AnimatedKPICard key={kpi.id} kpi={kpi} index={i} />
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">KPIs will appear once your data is analyzed.</div>
        )}
      </section>

      {/* Charts — backend-driven */}
      {charts.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Visualizations</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {charts.slice(0, 2).map((chart: any, ci: number) => (
              <div key={chart.id || ci} className="premium-card bg-card border border-border rounded-xl p-5 cursor-default">
                <div className="flex items-center justify-between mb-4">
                  <p className="text-sm font-semibold text-foreground">{chart.title}</p>
                </div>
                {chart.type === "area" || chart.type === "bar" ? (
                  <ResponsiveContainer width="100%" height={200}>
                    {chart.type === "area" ? (
                      <AreaChart data={chart.data}>
                        <defs>
                          <linearGradient id={`chartGrad-${ci}`} x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.15} />
                            <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                        <XAxis dataKey={chart.xKey || "period"} tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} width={55} tickFormatter={(v) => chart.format === "currency" ? `$${(v / 1000).toFixed(0)}K` : v.toLocaleString()} />
                        <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 11 }} labelStyle={{ color: "var(--foreground)", fontWeight: 600 }} formatter={(v: any) => [chart.format === "currency" ? `$${Number(v).toLocaleString()}` : Number(v).toLocaleString(), ""]} />
                        <Area type="monotone" dataKey={chart.dataKey || "value"} stroke="var(--primary)" strokeWidth={2} fill={`url(#chartGrad-${ci})`} dot={false} />
                      </AreaChart>
                    ) : (
                      <BarChart data={chart.data} barSize={28}>
                        <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                        <XAxis dataKey={chart.xKey || "name"} tick={{ fontSize: 9, fill: axis }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} width={55} tickFormatter={(v) => chart.format === "currency" ? `$${(v / 1000).toFixed(0)}K` : v.toLocaleString()} />
                        <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 11 }} labelStyle={{ color: "var(--foreground)", fontWeight: 600 }} formatter={(v: any) => [chart.format === "currency" ? `$${Number(v).toLocaleString()}` : Number(v).toLocaleString(), ""]} />
                        <Bar dataKey={chart.dataKey || "value"} fill="var(--primary)" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    )}
                  </ResponsiveContainer>
                ) : chart.type === "donut" ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie data={chart.data} cx="50%" cy="50%" innerRadius={55} outerRadius={85} dataKey="value" paddingAngle={2}>
                        {chart.data.map((entry: any, i: number) => (
                          <Cell key={i} fill={entry.fill || "#4F46E5"} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 11 }} formatter={(v: any) => [Number(v).toLocaleString(), ""]} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-[200px] flex items-center justify-center text-muted-foreground text-xs">No data available</div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ARIA Intelligence — backend-driven sections */}
      {sections.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">ARIA Intelligence</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {sections.map((section: any, idx: number) => (
              <SectionCard key={idx} section={section} setPage={setPage} />
            ))}
          </div>
        </section>
      )}

      {/* Fallback: show insightResult if no sections yet */}
      {sections.length === 0 && insights.length > 0 && (
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">ARIA Intelligence</h3>
            <button onClick={() => setPage("insights")} className="text-xs text-primary hover:underline flex items-center gap-1 font-medium">View all <ChevronRight size={12} /></button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {insights.slice(0, 4).map((ins: any, idx: number) => (
              <div key={idx} className="premium-card bg-card border border-border rounded-xl p-4 flex gap-3">
                <div className="mt-1 w-2 h-2 rounded-full flex-shrink-0 bg-primary" />
                <div className="flex-1 min-w-0 space-y-1">
                  <p className="text-sm font-medium text-foreground leading-snug">{ins.title}</p>
                  <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{ins.description}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Data Quality */}
      {quality.score > 0 && quality.score < 100 && quality.issues?.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Data Quality</h3>
          <div className="premium-card bg-card border border-border rounded-xl p-5">
            <div className="flex items-center gap-3 mb-3">
              <div className="text-2xl font-bold text-foreground">{quality.score}%</div>
              <div className="text-xs text-muted-foreground">Quality Score</div>
            </div>
            <div className="space-y-2">
              {quality.issues.slice(0, 5).map((issue: any, i: number) => (
                <div key={i} className="flex items-center gap-2 text-xs">
                  <div className={`w-1.5 h-1.5 rounded-full ${issue.severity === "critical" ? "bg-negative" : "bg-yellow-500"}`} />
                  <span className="text-muted-foreground">{issue.field}: {issue.issue}</span>
                </div>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
