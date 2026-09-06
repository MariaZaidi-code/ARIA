import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Database,
  Table2,
  Activity,
  FileText,
  Send,
  Loader2,
  Sparkles,
  ArrowLeft,
  MessageSquare,
  TrendingUp,
  TrendingDown,
  DollarSign,
  Users,
  ShoppingCart,
  BarChart3,
} from "lucide-react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import AriaLogo from "../components/AriaLogo";
import { fetchSchemaSummary } from "../services/api";

const pieColors = ["#2563eb", "#7c3aed", "#0ea5e9", "#f59e0b", "#10b981", "#ef4444", "#f97316"];

function ChartRenderer({ chart }) {
  if (!chart || !Array.isArray(chart.data) || chart.data.length === 0) return null;
  const { type, data, xKey, yKey, nameKey, valueKey } = chart;

  if (type === "line") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 30 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip />
          <Line type="monotone" dataKey={yKey} stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (type === "bar") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <BarChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 30 }}>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip />
          <Bar dataKey={yKey} fill="#2563eb" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (type === "donut" || type === "pie") {
    const nk = nameKey || xKey;
    const vk = valueKey || yKey;
    return (
      <div style={{ display: "flex", alignItems: "center", gap: 20, flexWrap: "wrap" }}>
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie data={data} dataKey={vk} nameKey={nk} cx="50%" cy="50%" innerRadius={type === "donut" ? 45 : 0} outerRadius={70} paddingAngle={2}>
              {data.map((_, i) => <Cell key={i} fill={pieColors[i % pieColors.length]} />)}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 120 }}>
          {data.slice(0, 5).map((item, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12 }}>
              <span style={{ width: 8, height: 8, borderRadius: "50%", background: pieColors[i % pieColors.length], flexShrink: 0 }} />
              <span style={{ color: "var(--aria-text-muted)" }}>{item[nk]}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (type === "area") {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data} margin={{ top: 10, right: 20, left: 10, bottom: 30 }}>
          <defs>
            <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#2563eb" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#2563eb" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={xKey} tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip />
          <Area type="monotone" dataKey={yKey} stroke="#2563eb" strokeWidth={2} fill="url(#areaGrad)" />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  return null;
}

function useCountUp(target) {
  const [display, setDisplay] = useState(target);

  useEffect(() => {
    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReducedMotion) return;

    const duration = 700;
    const start = performance.now();
    let frame;

    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(Math.round(target * eased));
      if (progress < 1) frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target]);

  return display;
}

function Dashboard({
  submittedQuestion,
  normalizedResult,
  connectionStatus,
  dbName,
  selectedSourceType,
  selectedFile,
  schemaData,
  currentUser,
  handleSuggestionSelect,
  onQuickAsk,
  onNavigate,
  onRetry,
  goalStatus,
  goalError,
  questionSuggestions,
  suggestionsLoading,
}) {
  const [quickAskValue, setQuickAskValue] = useState("");
  const [schemaSummary, setSchemaSummary] = useState(null);

  const isConnected = connectionStatus === "connected";
  const isGoalRunning = goalStatus === "running";
  const isGoalSuccess = goalStatus === "success";
  const isGoalFailed = goalStatus === "failed";
  const isShowingResult = submittedQuestion && (isGoalSuccess || isGoalFailed || isGoalRunning);

  useEffect(() => {
    if (!isConnected) return;
    let cancelled = false;
    fetchSchemaSummary().then((result) => {
      if (!cancelled && result.data) setSchemaSummary(result.data);
    });
    return () => { cancelled = true; };
  }, [isConnected]);

  const schemaTables = schemaData?.tables || {};
  const schemaTableCount = schemaSummary?.table_count || Object.keys(schemaTables).length;
  const tableCountLabel = schemaTableCount > 0 ? `${schemaTableCount} table${schemaTableCount === 1 ? "" : "s"}` : "Not analyzed";

  const allSessions = JSON.parse(localStorage.getItem("aria_history_sessions") || "[]");
  const analysisCount = allSessions.length;
  const savedCount = allSessions.filter((s) => s.savedReport).length;

  const getConnectedSourceName = () => {
    if (selectedSourceType === "csv" || selectedSourceType === "pdf") return selectedFile?.name || "Uploaded file";
    return dbName || "Connected database";
  };

  const greeting = (() => {
    const hour = new Date().getHours();
    if (hour < 12) return "Good morning";
    if (hour < 17) return "Good afternoon";
    return "Good evening";
  })();

  const maybeSubmitQuickAsk = () => {
    if (!quickAskValue.trim() || !isConnected) return;
    if (onQuickAsk) onQuickAsk(quickAskValue);
    setQuickAskValue("");
  };

  const handleBackToLanding = () => {
    if (onRetry) onRetry();
  };

  const kpiStats = [
    { label: "Revenue", value: 1284750, icon: <DollarSign size={20} />, prefix: "$", delta: "+12.5%", positive: true, support: "vs last month" },
    { label: "Customers", value: 3842, icon: <Users size={20} />, delta: "+8.2%", positive: true, support: "active users" },
    { label: "Orders", value: 1284, icon: <ShoppingCart size={20} />, delta: "-3.1%", positive: false, support: "this period" },
    { label: "Growth", value: 34, icon: <BarChart3 size={20} />, suffix: "%", delta: "+5.4%", positive: true, support: "month over month" },
  ];

  const charts = normalizedResult?.charts || [];

  return (
    <div className="dashboard-layout">
      {/* MAIN CONTENT */}
      <div className="dashboard-main">
        {/* RESULT VIEW */}
        {isShowingResult && (
          <div className="dashboard-result-view">
            <div className="dashboard-result-header">
              <button type="button" className="dashboard-back-btn" onClick={handleBackToLanding}>
                <ArrowLeft size={16} /> Back
              </button>
              <div>
                <span className="dashboard-eyebrow">Analysis</span>
                <h2>{submittedQuestion}</h2>
              </div>
            </div>

            {isGoalRunning && (
              <section className="section-card" style={{ textAlign: "center", padding: 40 }}>
                <Loader2 size={24} className="spin" style={{ color: "var(--aria-accent)", marginBottom: 12 }} />
                <p style={{ margin: 0, color: "var(--aria-text-muted)" }}>Analyzing your data...</p>
              </section>
            )}

            {isGoalFailed && (
              <section className="section-card">
                <div style={{ textAlign: "center", padding: 20 }}>
                  <p style={{ margin: "0 0 12px", color: "var(--aria-error)" }}>ARIA couldn't complete this request.</p>
                  {goalError && <details className="error-details-collapse"><summary>View details</summary><p className="error-detail">{goalError}</p></details>}
                  <button type="button" className="primary-button" onClick={() => onRetry && onRetry()}>Try again</button>
                </div>
              </section>
            )}

            {isGoalSuccess && normalizedResult && (
              <>
                {normalizedResult.summary && (
                  <section className="section-card">
                    <div className="section-card-label">Executive Summary</div>
                    <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6 }}>{normalizedResult.summary}</p>
                  </section>
                )}

                {normalizedResult.metrics?.length > 0 && (
                  <div className="dashboard-kpi-grid">
                    {normalizedResult.metrics.map((metric, index) => (
                      <motion.div className="dashboard-kpi-card" key={index} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: index * 0.06, duration: 0.35 }}>
                        <span className="dashboard-kpi-label">{metric.label}</span>
                        <strong className="dashboard-kpi-value">{metric.formattedValue}</strong>
                      </motion.div>
                    ))}
                  </div>
                )}

                {charts.length > 0 && (
                  <div className="dashboard-charts-grid">
                    {charts.slice(0, 2).map((chart, index) => (
                      <section className="section-card" key={index}>
                        <div className="section-card-label">{chart.title}</div>
                        <ChartRenderer chart={chart} />
                      </section>
                    ))}
                  </div>
                )}

                {normalizedResult.keyFindings?.length > 0 && (
                  <section className="section-card">
                    <div className="section-card-label">Key Findings</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                      {normalizedResult.keyFindings.map((finding, index) => (
                        <div key={index} className="dashboard-finding">
                          <span className="dashboard-finding-num">{String(index + 1).padStart(2, "0")}</span>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 600 }}>{finding.title}</div>
                            <div style={{ fontSize: 12, color: "var(--aria-text-muted)", marginTop: 2 }}>{finding.description}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </section>
                )}

                {normalizedResult.recommendations?.length > 0 && (
                  <section className="section-card">
                    <div className="section-card-label">Recommendations</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                      {normalizedResult.recommendations.map((rec, index) => (
                        <div key={index} className="dashboard-recommendation">
                          <span style={{ fontSize: 12, fontWeight: 700, color: "var(--aria-accent)" }}>→</span>
                          <span style={{ fontSize: 13 }}>{rec.title}</span>
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </>
            )}
          </div>
        )}

        {/* LANDING VIEW */}
        {!isShowingResult && (
          <div className="dashboard-landing">
            {/* Executive Summary Header */}
            <div className="dashboard-exec-header">
              <div className="dashboard-exec-title">
                <div className="dashboard-exec-icon">
                  <Sparkles size={20} />
                </div>
                <div>
                  <h1>Executive Summary</h1>
                  <p>Track your company&apos;s plan and most important KPIs progress</p>
                </div>
              </div>
              <div className="dashboard-filters">
                <span className="dashboard-filter">Scenario: Base Case</span>
                <span className="dashboard-filter">Region: All values</span>
                <span className="dashboard-filter">Year: FY 24</span>
              </div>
            </div>

            {/* KPI Cards - Colored like Pigment */}
            <div className="dashboard-kpi-colored-grid">
              {kpiStats.map((stat, index) => (
                <motion.div
                  className={`dashboard-kpi-colored-card kpi-color-${index}`}
                  key={stat.label}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.1 + index * 0.06, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                >
                  <strong className="dashboard-kpi-colored-value">
                    {stat.prefix || ""}{typeof stat.value === "number" ? stat.value.toLocaleString() : stat.value}{stat.suffix || ""}
                  </strong>
                  <span className="dashboard-kpi-colored-delta stat">{stat.delta} {stat.support}</span>
                  <span className="dashboard-kpi-colored-label">{stat.label}</span>
                </motion.div>
              ))}
            </div>

            {/* Charts Grid */}
            {charts.length > 0 && (
              <div className="dashboard-charts-grid">
                {charts.slice(0, 2).map((chart, index) => (
                  <section className="section-card" key={index}>
                    <div className="section-card-label">{chart.title}</div>
                    <ChartRenderer chart={chart} />
                  </section>
                ))}
              </div>
            )}

            {/* Data Source Info */}
            {isConnected && (
              <div className="dashboard-source-info">
                <div className="section-card">
                  <div className="section-card-head">
                    <h3>Connected Source</h3>
                  </div>
                  <div className="dashboard-source-content">
                    <div className="dashboard-source-item">
                      <span className="dashboard-status-dot connected" />
                      <div>
                        <strong>{getConnectedSourceName()}</strong>
                        <span>{tableCountLabel}</span>
                      </div>
                    </div>
                    {schemaSummary?.table_names?.length > 0 && (
                      <div className="dashboard-table-tags">
                        {schemaSummary.table_names.slice(0, 5).map((name) => (
                          <span key={name} className="dashboard-table-tag">{name}</span>
                        ))}
                        {schemaTableCount > 5 && <span className="dashboard-table-tag-more">+{schemaTableCount - 5}</span>}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Quick Actions */}
            <div className="dashboard-quick-actions-grid">
              <button type="button" className="dashboard-quick-action" onClick={() => onNavigate && onNavigate("askAria")}>
                <MessageSquare size={18} />
                <span>Copilot</span>
                <small>Chat with ARIA</small>
              </button>
              <button type="button" className="dashboard-quick-action" onClick={() => onNavigate && onNavigate("insights")}>
                <Sparkles size={18} />
                <span>Insights</span>
                <small>View business insights</small>
              </button>
              <button type="button" className="dashboard-quick-action" onClick={() => onNavigate && onNavigate("schema")}>
                <Table2 size={18} />
                <span>Schema</span>
                <small>Explore your data</small>
              </button>
              <button type="button" className="dashboard-quick-action" onClick={() => onNavigate && onNavigate("history")}>
                <Activity size={18} />
                <span>History</span>
                <small>View past analyses</small>
              </button>
            </div>
          </div>
        )}
      </div>

      {/* FLOATING AI PANEL - Right Side like Pigment */}
      <div className="dashboard-ai-panel">
        <div className="ai-panel-header">
          <AriaLogo size={16} />
          <span>ARIA Intelligence</span>
        </div>

        <div className="ai-panel-content">
          <h3>Ask a question or start with one of the following:</h3>

          {/* Suggested Questions */}
          {isConnected && questionSuggestions?.length > 0 && (
            <div className="ai-panel-suggestions">
              {questionSuggestions.slice(0, 3).map((suggestion, index) => (
                <button
                  type="button"
                  className="ai-suggestion-item"
                  key={`${suggestion}-${index}`}
                  onClick={() => {
                    if (onQuickAsk) onQuickAsk(suggestion);
                  }}
                >
                  <Sparkles size={12} />
                  <span>{suggestion}</span>
                </button>
              ))}
            </div>
          )}

          {isConnected && suggestionsLoading && questionSuggestions.length === 0 && (
            <div className="ai-panel-suggestions">
              {[0, 1, 2].map((i) => <div className="skeleton skeleton-suggestion" key={i} />)}
            </div>
          )}
        </div>

        {/* Input */}
        <div className="ai-panel-input-wrapper">
          <input
            type="text"
            className="ai-panel-input"
            value={quickAskValue}
            onChange={(e) => setQuickAskValue(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") maybeSubmitQuickAsk(); }}
            placeholder={isConnected ? "Ask a question..." : "Connect a data source first"}
            disabled={!isConnected}
          />
          <button
            type="button"
            className="ai-panel-submit"
            onClick={maybeSubmitQuickAsk}
            disabled={!isConnected || !quickAskValue.trim()}
          >
            <Send size={16} />
          </button>
        </div>

        {!isConnected && (
          <button type="button" className="ai-panel-connect" onClick={() => onNavigate && onNavigate("dataSourceSelect")}>
            <Database size={14} /> Connect data source
          </button>
        )}
      </div>
    </div>
  );
}

export default Dashboard;
