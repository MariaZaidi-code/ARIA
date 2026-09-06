import { motion } from "framer-motion";
import {
  BarChart3,
  LayoutDashboard,
  Table2,
} from "lucide-react";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  AreaChart,
  Area,
} from "recharts";

const PIE_COLORS = [
  "#2563eb",
  "#7c3aed",
  "#0891b2",
  "#059669",
  "#d97706",
  "#dc2626",
  "#4f46e5",
  "#0f766e",
];

const humanize = (key) =>
  String(key || "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

const formatValue = (value) => {
  if (typeof value !== "number") return value;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(value);
};

const compact = (value) =>
  typeof value === "number"
    ? new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)
    : value;

function ChartView({ chart }) {
  if (!chart || !Array.isArray(chart.data) || chart.data.length === 0) {
    return (
      <div className="chart-unavailable">No data available for this chart.</div>
    );
  }

  const axisTick = { fill: "var(--aria-text-muted)", fontSize: 11 };
  const grid = "var(--aria-border)";

  if (chart.type === "line") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chart.data} margin={{ top: 15, right: 25, left: 10, bottom: 40 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={chart.xKey} tickLine={false} axisLine={false} tick={axisTick} />
          <YAxis tickFormatter={compact} tickLine={false} axisLine={false} tick={axisTick} />
          <Tooltip />
          <Line type="monotone" dataKey={chart.yKey} name={chart.yLabel || humanize(chart.yKey)} stroke="#2563eb" strokeWidth={3} dot={{ r: 4 }} />
        </LineChart>
      </ResponsiveContainer>
    );
  }

  if (chart.type === "area") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <AreaChart data={chart.data} margin={{ top: 15, right: 25, left: 10, bottom: 40 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={chart.xKey} tickLine={false} axisLine={false} tick={axisTick} />
          <YAxis tickFormatter={compact} tickLine={false} axisLine={false} tick={axisTick} />
          <Tooltip />
          <Area type="monotone" dataKey={chart.yKey} name={chart.yLabel || humanize(chart.yKey)} stroke="#2563eb" fill="#bfdbfe" strokeWidth={3} />
        </AreaChart>
      </ResponsiveContainer>
    );
  }

  if (chart.type === "bar") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={chart.data} margin={{ top: 15, right: 25, left: 10, bottom: 60 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey={chart.xKey} tickLine={false} axisLine={false} tick={axisTick} interval={0} angle={-25} textAnchor="end" height={70} />
          <YAxis tickFormatter={compact} tickLine={false} axisLine={false} tick={axisTick} />
          <Tooltip />
          <Bar dataKey={chart.yKey} name={chart.yLabel || humanize(chart.yKey)} fill="#2563eb" radius={[6, 6, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart.type === "horizontal-bar") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <BarChart layout="vertical" data={chart.data} margin={{ top: 15, right: 30, left: 90, bottom: 30 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tickFormatter={compact} tickLine={false} axisLine={false} tick={axisTick} />
          <YAxis type="category" dataKey={chart.xKey} width={170} tickLine={false} axisLine={false} tick={axisTick} />
          <Tooltip />
          <Bar dataKey={chart.yKey} name={chart.yLabel || humanize(chart.yKey)} fill="#2563eb" radius={[0, 6, 6, 0]} />
        </BarChart>
      </ResponsiveContainer>
    );
  }

  if (chart.type === "pie" || chart.type === "donut") {
    const nameKey = chart.nameKey || chart.xKey;
    const valueKey = chart.valueKey || chart.yKey;
    return (
      <div style={{ width: "100%", height: 300, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <ResponsiveContainer width="60%" height={300} minWidth={240}>
          <PieChart>
            <Tooltip />
            <Pie
              data={chart.data}
              dataKey={valueKey}
              nameKey={nameKey}
              cx="50%"
              cy="50%"
              innerRadius={chart.type === "donut" ? 70 : 0}
              outerRadius={110}
              label={chart.type === "pie" ? ({ name, percent }) => `${name}: ${Math.round((percent || 0) * 100)}%` : false}
              labelLine={chart.type === "pie"}
            >
              {chart.data.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      </div>
    );
  }

  if (chart.type === "scatter") {
    return (
      <ResponsiveContainer width="100%" height={280}>
        <ScatterChart margin={{ top: 15, right: 25, left: 10, bottom: 40 }}>
          <CartesianGrid stroke={grid} strokeDasharray="3 3" />
          <XAxis type="number" dataKey={chart.xKey} name={chart.xLabel || humanize(chart.xKey)} tickFormatter={compact} tickLine={false} axisLine={false} tick={axisTick} />
          <YAxis type="number" dataKey={chart.yKey} name={chart.yLabel || humanize(chart.yKey)} tickFormatter={compact} tickLine={false} axisLine={false} tick={axisTick} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} />
          <Scatter data={chart.data} fill="#2563eb" />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  return <div className="chart-unavailable">Unsupported chart type.</div>;
}

function AnalyticsPage({ analysisResult, loading, connectionStatus, onStartAnalysis }) {
  const isConnected = connectionStatus === "connected";

  const kpis = Array.isArray(analysisResult?.kpis) ? analysisResult.kpis : [];
  const charts = Array.isArray(analysisResult?.charts) ? analysisResult.charts : [];
  const table = analysisResult?.table;

  const hasAnalytics = kpis.length > 0 || charts.length > 0;
  const empty = !hasAnalytics && !loading;

  return (
    <div className="dashboard-page">
      {loading && (
        <section className="section-card">
          <div className="insights-placeholder">
            <span className="ask-submit-spinner" aria-hidden="true" />
            <p>Building your analytics…</p>
          </div>
        </section>
      )}

      {empty && (
        <motion.section
          className="section-card"
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
        >
          <div className="insights-empty">
            <span className="insights-empty-icon" aria-hidden="true">
              <BarChart3 size={32} strokeWidth={1.5} />
            </span>
            <h3>No analytics yet</h3>
            <p>
              {isConnected
                ? "Run an analysis to explore trends and distributions in your data."
                : "Connect a data source to start exploring your data."}
            </p>
            {isConnected && (
              <button type="button" className="primary-button" onClick={onStartAnalysis}>
                Start an analysis
              </button>
            )}
          </div>
        </motion.section>
      )}

      {hasAnalytics && (
        <div className="analytics-page">
          {kpis.length > 0 && (
            <div className="analytics-kpi-grid">
              {kpis.map((kpi, index) => (
                <div className="analytics-kpi-card" key={`${kpi.label}-${index}`}>
                  <span className="analytics-kpi-label">{kpi.label}</span>
                  <strong className="analytics-kpi-value">{kpi.value}</strong>
                </div>
              ))}
            </div>
          )}

          {charts.length > 0 && (
            <div className="analytics-chart-grid">
              {charts.map((chart, index) => (
                <motion.section
                  className="section-card"
                  key={`chart-${index}`}
                  initial={{ opacity: 0, y: 16 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.06, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
                >
                  <div className="insights-card-head">
                    <span className="insights-card-icon" aria-hidden="true">
                      <LayoutDashboard size={18} strokeWidth={2} />
                    </span>
                    <h3>{chart.title || "Visualization"}</h3>
                  </div>
                  <ChartView chart={chart} />
                </motion.section>
              ))}
            </div>
          )}

          {table && Array.isArray(table.rows) && table.rows.length > 0 && (
            <motion.section
              className="section-card full-bleed"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            >
              <div className="insights-card-head">
                <span className="insights-card-icon" aria-hidden="true">
                  <Table2 size={18} strokeWidth={2} />
                </span>
                <h3>Data</h3>
              </div>
              <div className="analytics-table-wrap">
                <table className="analytics-table">
                  <thead>
                    <tr>
                      {table.columns.map((col) => (
                        <th key={col.key}>{col.label || humanize(col.key)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.map((row, rowIndex) => (
                      <tr key={rowIndex}>
                        {table.columns.map((col) => (
                          <td key={col.key}>{formatValue(row[col.key]) ?? "—"}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </motion.section>
          )}
        </div>
      )}
    </div>
  );
}

export default AnalyticsPage;
