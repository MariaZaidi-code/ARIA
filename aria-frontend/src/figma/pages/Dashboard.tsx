import { useState, useEffect } from "react";
import { ArrowRight, ArrowUpRight, ArrowDownRight, Zap, Search, AlertTriangle, ChevronRight } from "lucide-react";
import { AreaChart, Area, BarChart, Bar, ResponsiveContainer, Tooltip, CartesianGrid, XAxis, YAxis } from "recharts";
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
}

const fmt = (n: number, prefix = "") =>
  n >= 1_000_000 ? `${prefix}${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000 ? `${prefix}${(n / 1_000).toFixed(1)}K`
    : `${prefix}${n.toLocaleString()}`;

const examples = [
  "Why did sales decrease last month?",
  "Which products are performing best?",
  "Forecast next month's revenue",
  "Find unusual changes in sales",
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

const sparkData = {
  revenue: [194, 218, 207, 248, 279, 261, 301, 291, 341, 378, 552, 684].map((v) => ({ v })),
  sales: [12400, 13800, 13200, 15600, 17200, 16400, 18700, 18100, 21000, 23200, 33700, 43400].map((v) => ({ v })),
  orders: [3820, 4100, 3960, 4550, 5010, 4780, 5420, 5280, 6100, 6740, 9820, 12640].map((v) => ({ v })),
  customers: [680, 740, 710, 820, 900, 860, 980, 950, 1080, 1190, 1730, 2230].map((v) => ({ v })),
  profit: [149, 168, 159, 191, 214, 201, 231, 224, 261, 290, 424, 526].map((v) => ({ v })),
};

function KPICard({ label, value, change, prefix = "", period, sparkKey }: {
  label: string; value: number; change: number; prefix?: string; period: string; sparkKey?: keyof typeof sparkData;
}) {
  const positive = change >= 0;
  const data = sparkKey ? sparkData[sparkKey] : [{ v: value }];
  return (
    <div className="premium-card stat-top bg-card border border-border rounded-xl p-4 flex flex-col gap-2 cursor-default overflow-hidden relative">
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">{label}</p>
        <span className={`flex items-center gap-0.5 text-[11px] font-semibold px-1.5 py-0.5 rounded-full ${positive ? "text-positive bg-positive/10" : "text-negative bg-negative/10"}`}>
          {positive ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
          {Math.abs(change)}%
        </span>
      </div>
      <p className="text-[22px] font-bold text-foreground tracking-tight">{fmt(value, prefix)}</p>
      <div className="h-8 -mx-1">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id={`spark-${label}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.2} />
                <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area type="monotone" dataKey="v" stroke="var(--primary)" strokeWidth={1.5} fill={`url(#spark-${label})`} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[11px] text-muted-foreground">{period}</p>
    </div>
  );
}

export default function Dashboard({ setPage, onAsk, user, connectionStatus = "not-connected", dbName = "", insightResult = null, analysisResult = null }: DashboardProps) {
  const { isDark } = useTheme();
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [kpis, setKpis] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  useEffect(() => {
    if (connectionStatus === "connected") {
      fetchDashboardKPIs();
      fetchSuggestions();
    }
  }, [connectionStatus]);

  const fetchSuggestions = async () => {
    try {
      const res = await fetch("/api/suggestions", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${localStorage.getItem("aria_auth_token") || ""}` },
        body: JSON.stringify({ limit: 6, use_llm: true }),
      });
      if (res.ok) {
        const data = await res.json();
        if (data.suggestions && Array.isArray(data.suggestions)) setSuggestions(data.suggestions);
        else if (data.ok && Array.isArray(data.suggestions)) setSuggestions(data.suggestions);
      }
    } catch (e) { console.error("Suggestions fetch failed:", e); }
  };

  const fetchDashboardKPIs = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/dashboard/kpis", { headers: { Authorization: `Bearer ${localStorage.getItem("aria_auth_token")}` } });
      const data = await res.json();
      if (data.ok) setKpis(data.kpis || []);
    } catch (e) { console.error("Failed to fetch KPIs:", e); } finally { setLoading(false); }
  };

  const handleSubmit = () => { if (query.trim()) { onAsk?.(query.trim()); setPage("analytics"); } };

  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-20 animate-fade-in">
          <div className="w-16 h-16 rounded-2xl mx-auto mb-5 flex items-center justify-center" style={{ background: 'var(--gradient-primary)' }}>
            <Search size={24} className="text-white" />
          </div>
          <h2 className="text-2xl font-bold text-foreground mb-2">Connect a Data Source</h2>
          <p className="text-sm text-muted-foreground mb-6 max-w-sm mx-auto">Get started by connecting your database or uploading a file to unlock AI-powered insights.</p>
          <button onClick={() => setPage("data")} className="premium-btn btn-glow px-6 py-2.5 rounded-xl text-sm font-semibold text-white transition-all" style={{ background: 'var(--gradient-primary)' }}>Connect Now</button>
        </div>
      </div>
    );
  }

  const insights = insightResult?.keyInsights || insightResult?.insights || [];
  const anomalies = insightResult?.anomalies || [];

  // Build KPI list: use API data if available, otherwise show empty state
  const kpiList = kpis.length > 0 ? kpis : [];

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-8">
      {/* Greeting + Query */}
      <div className="space-y-4 animate-fade-in">
        <div>
          <h2 className="text-2xl font-bold text-foreground tracking-tight">Good morning, {user?.email?.split("@")[0] || "User"}</h2>
          <p className="text-sm text-muted-foreground mt-1">Here's what ARIA found in your business data.</p>
        </div>
        <div className="relative">
          <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3 focus-within:border-primary/50 focus-within:shadow-[0_0_0_3px_var(--primary-light)] transition-all duration-200" style={{ boxShadow: 'var(--shadow-sm)' }}>
            <Search size={16} className="text-muted-foreground flex-shrink-0" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 150)} onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
              placeholder="Ask ARIA anything about your business..." className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none" />
            <button onClick={handleSubmit} className="premium-btn btn-glow flex-shrink-0 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all" style={{ background: 'var(--gradient-primary)' }}>Ask</button>
          </div>
          {showSuggestions && (
            <div className="absolute top-full left-0 right-0 mt-2 bg-card border border-border rounded-xl shadow-lg py-1 z-20">
              {(suggestions.length ? suggestions : examples).map((ex) => (
                <button key={ex} onMouseDown={() => { setQuery(ex); onAsk?.(ex); setPage("analytics"); }}
                  className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-foreground hover:bg-secondary transition-colors text-left">
                  <Zap size={13} className="text-primary flex-shrink-0" />{ex}
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {(suggestions.length ? suggestions : examples).map((ex) => (
            <button key={ex} onClick={() => { setQuery(ex); onAsk?.(ex); setPage("analytics"); }}
              className="text-xs px-3 py-1.5 rounded-full bg-secondary hover:bg-secondary/70 text-muted-foreground hover:text-foreground transition-colors border border-border">
              {ex}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Cards */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Business Overview</h3>
        {loading ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
            {[1,2,3,4,5].map((i) => (
              <div key={i} className="bg-card border border-border rounded-xl p-4 animate-pulse">
                <div className="h-3 bg-secondary rounded w-16 mb-3" />
                <div className="h-6 bg-secondary rounded w-24 mb-2" />
                <div className="h-8 bg-secondary rounded w-full" />
              </div>
            ))}
          </div>
        ) : kpiList.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 stagger-children">
            {kpiList.map((kpi: any) => (
              <KPICard
                key={kpi.label || kpi.name}
                label={kpi.label || kpi.name || "Metric"}
                value={kpi.value || kpi.total || 0}
                change={kpi.change || kpi.change_pct || 0}
                prefix={kpi.prefix || ""}
                period={kpi.period || "vs prior period"}
              />
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">
            {connectionStatus === "connected"
              ? "KPIs will appear once your data is analyzed."
              : "Connect a data source to see KPIs."}
          </div>
        )}
      </section>

      {/* ARIA Intelligence */}
      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider section-premium">ARIA Intelligence</h3>
          <button onClick={() => setPage("insights")} className="text-xs text-primary hover:underline flex items-center gap-1 premium-btn font-medium">View all <ChevronRight size={12} /></button>
        </div>
        {insights.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 stagger-children">
            {insights.slice(0, 4).map((ins: any, idx: number) => (
              <div key={idx} className="premium-card bg-card border border-border rounded-xl p-4 flex gap-3 cursor-default">
                <div className={`mt-1 w-2 h-2 rounded-full flex-shrink-0 ${severityDot[ins.impact] || "bg-primary"}`} />
                <div className="flex-1 min-w-0 space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-medium text-foreground leading-snug">{ins.title}</p>
                    <span className={`flex-shrink-0 text-[10px] font-medium px-2 py-0.5 rounded-full ${typeColor[ins.impact] || "text-primary bg-primary/10"}`}>{ins.impact || "Insight"}</span>
                  </div>
                  <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{ins.description}</p>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3 text-[11px]">
                      {ins.magnitude && <span className={`font-medium ${ins.magnitude.startsWith("+") ? "text-positive" : "text-negative"}`}>{ins.magnitude}</span>}
                      {ins.confidence && <span className="text-muted-foreground">{ins.confidence}% confidence</span>}
                    </div>
                    <button onClick={() => setPage("insights")} className="text-[11px] text-primary hover:underline">Explore →</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">No insights available yet.</div>
        )}
      </section>

      {/* Analytics Overview */}
      <section className="space-y-3">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider section-premium">Analytics Overview</h3>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 stagger-children">
          <div className="premium-card bg-card border border-border rounded-xl p-5 cursor-default">
            <div className="flex items-center justify-between mb-4">
              <p className="text-sm font-semibold text-foreground">Revenue Trend</p>
              {analysisResult?.kpis?.revenue?.change_pct != null && (
                <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-full ${analysisResult.kpis.revenue.change_pct >= 0 ? "text-positive bg-positive/10" : "text-negative bg-negative/10"}`}>
                  {analysisResult.kpis.revenue.change_pct >= 0 ? "+" : ""}{analysisResult.kpis.revenue.change_pct}%
                </span>
              )}
            </div>
            {analysisResult?.charts?.revenue_trend ? (
              <ResponsiveContainer width="100%" height={180}>
                <AreaChart data={analysisResult.charts.revenue_trend}>
                  <defs>
                    <linearGradient id="revGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="var(--primary)" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}K`} />
                  <Tooltip
                    contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 11, boxShadow: "var(--shadow-md)" }}
                    labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                  />
                  <Area type="monotone" dataKey="value" stroke="var(--primary)" strokeWidth={2} fill="url(#revGrad)" dot={false} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[180px] flex items-center justify-center text-muted-foreground text-xs">
                Run an analysis to see revenue trends.
              </div>
            )}
          </div>
          <div className="premium-card bg-card border border-border rounded-xl p-5 cursor-default">
            <div className="flex items-center justify-between mb-4">
              <div>
                <p className="text-sm font-semibold text-foreground">Category Performance</p>
                <p className="text-[11px] text-muted-foreground mt-0.5">Revenue by category</p>
              </div>
            </div>
            {analysisResult?.charts?.category_breakdown ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={analysisResult.charts.category_breakdown} barSize={28}>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 9, fill: axis }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 10, fill: axis }} axisLine={false} tickLine={false} width={48} tickFormatter={(v) => `$${(v / 1000).toFixed(0)}K`} />
                  <Tooltip
                    contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 11, boxShadow: "var(--shadow-md)" }}
                    labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    formatter={(v: any) => [`$${(v / 1000).toFixed(0)}K`, "Revenue"]}
                  />
                  <Bar dataKey="revenue" fill="var(--primary)" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[180px] flex items-center justify-center text-muted-foreground text-xs">
                Run an analysis to see category breakdown.
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Detected Anomalies */}
      {anomalies.length > 0 && (
        <section className="space-y-3">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-1.5 section-premium">
            <AlertTriangle size={12} /> Detected Anomalies
          </h3>
          <div className="bg-card border border-border rounded-xl overflow-hidden" style={{ boxShadow: 'var(--shadow-sm)' }}>
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
                {anomalies.slice(0, 5).map((a: any, i: number) => (
                  <tr key={i} className={`${i < anomalies.length - 1 ? "border-b border-border" : ""} hover:bg-secondary/30 transition-colors`}>
                    <td className="px-5 py-3 font-medium text-foreground text-sm">{a.title}</td>
                    <td className="px-5 py-3 text-muted-foreground text-xs">{a.date}</td>
                    <td className={`px-5 py-3 text-xs font-medium ${a.deviation.startsWith("-") ? "text-negative" : "text-positive"}`}>{a.deviation}</td>
                    <td className="px-5 py-3 text-muted-foreground text-xs hidden md:table-cell max-w-xs truncate">{a.explanation}</td>
                    <td className="px-5 py-3">
                      <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full capitalize ${a.severity === "high" ? "text-negative bg-negative/10" : a.severity === "medium" ? "text-warning bg-warning/10" : "text-positive bg-positive/10"}`}>{a.severity}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Recommended Questions */}
      <section className="space-y-3 pb-4">
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider section-premium">Recommended Questions</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 stagger-children">
          {[
            { q: "Why did revenue change so dramatically in November?", tag: "Revenue" },
            { q: "Which region is growing fastest and why?", tag: "Regional" },
            { q: "What will Q1 2026 revenue look like?", tag: "Forecast" },
            { q: "Which customers have the highest lifetime value?", tag: "Customers" },
          ].map(({ q, tag }) => (
            <button key={q} onClick={() => setPage("analytics")}
              className="premium-card flex items-center justify-between bg-card border border-border rounded-xl px-4 py-3.5 hover:border-primary/40 text-left group">
              <div className="space-y-1">
                <p className="text-sm text-foreground group-hover:text-primary transition-colors">{q}</p>
                <span className="text-[10px] text-muted-foreground bg-secondary px-2 py-0.5 rounded-full">{tag}</span>
              </div>
              <ArrowRight size={14} className="text-muted-foreground group-hover:text-primary transition-colors ml-3 flex-shrink-0" />
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
