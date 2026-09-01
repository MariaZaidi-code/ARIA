import { useEffect, useRef, useState } from "react";

function useFetchedHistory(currentUser) {
  const [fetchedHistorySessions, setFetchedHistorySessions] = useState([]);

  useEffect(() => {
    async function fetchHistory() {
      const token = localStorage.getItem("aria_auth_token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};

      try {
        const response = await fetch("/api/history", { headers });
        if (response.ok) {
          const data = await response.json();
          setFetchedHistorySessions(data.items || []);
        } else {
          console.error("Failed to fetch history");
        }
      } catch (error) {
        console.error("Error fetching history", error);
      }
    }

    fetchHistory();
  }, [currentUser?.email]);

  return fetchedHistorySessions;
}

function useFilteredHistory(fetchedHistory, currentUser) {
  return fetchedHistory.filter(
    (session) => !currentUser?.email || session.userEmail === currentUser.email,
  );
}

function useFormatRecentDate(dateValue) {
  if (!dateValue) {
    return "";
  }

  return new Date(dateValue).toLocaleString();
}

function useGetConnectedSourceName(isConnected, selectedSourceType, selectedFile, dbName) {
  if (!isConnected) {
    return "No data source connected";
  }

  if (selectedSourceType === "csv" || selectedSourceType === "pdf") {
    return selectedFile?.name || "Uploaded file";
  }

  if (selectedSourceType === "postgresql" || selectedSourceType === "mysql") {
    return dbName || "Connected database";
  }

  return "Connected source";
}

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
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";



function useCountUp(target) {
  const [display, setDisplay] = useState(0);

  const startedRef = useRef(false);

  useEffect(() => {
    if (startedRef.current) {
      setDisplay(target);

      return;
    }

    startedRef.current = true;

    const prefersReducedMotion =
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (prefersReducedMotion) {
      const skipTimer = setTimeout(() => setDisplay(target), 0);

      return () => clearTimeout(skipTimer);
    }

    const duration = 700;

    const start = performance.now();

    let frame;

    const tick = (now) => {
      const progress = Math.min((now - start) / duration, 1);

      const eased = 1 - Math.pow(1 - progress, 3);

      setDisplay(Math.round(target * eased));

      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      }
    };

    frame = requestAnimationFrame(tick);

    return () => cancelAnimationFrame(frame);
  }, [target]);

  return display;
}

function AnimatedKpiValue({ value }) {
  const display = useCountUp(value);

  return <strong className="dashboard-kpi-value">{display}</strong>;
}

function Dashboard({
  submittedQuestion,
  analysisResult,
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
  goalResult,
  goalError,

  insightStatus,
  insightResult,
  insightError,
  handleInsightRetry,

  feedbackStatus,
  submittedFeedback,
  feedbackError,
  handleFeedbackSubmit,
  handleSaveReport,
  currentHistorySessionId,
}) {
  // =========================================================
  // DAY 8 - USER FEEDBACK FORM STATES
  // =========================================================

  const [overallUseful, setOverallUseful] = useState(null);

  const [overallRating, setOverallRating] = useState(0);

  const [feedbackCorrection, setFeedbackCorrection] = useState("");

  const [reactionRating, setReactionRating] = useState(0);
  const [insightFeedback, setInsightFeedback] = useState({});

  const [anomalyFeedback, setAnomalyFeedback] = useState({});

  const [hypothesisFeedback, setHypothesisFeedback] = useState({});

  const [chartFeedback, setChartFeedback] = useState({});

  const [recommendationFeedback, setRecommendationFeedback] = useState({});

  const [bestHypothesis, setBestHypothesis] = useState(null);

  const [localReportSaved, setLocalReportSaved] = useState(false);

  // =========================================================
  // QUICK ASK + RECENT ACTIVITY (landing helpers)
  // =========================================================

  const [quickAskValue, setQuickAskValue] = useState("");

  const nowHour = new Date().getHours();

  const greetingName =
    nowHour < 5
      ? "Good evening"
      : nowHour < 12
        ? "Good morning"
        : nowHour < 18
          ? "Good afternoon"
          : "Good evening";

  const fetchedHistory = useFetchedHistory(currentUser);
  const recentSessions = useFilteredHistory(fetchedHistory, currentUser)
    .sort(
      (a, b) =>
        new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime(),
    )
    .slice(0, 5);

  const formatRecentDate = (dateValue) => {
    if (!dateValue) {
      return "";
    }

    return new Date(dateValue).toLocaleString();
  };

  // =========================================================
  // REAL KPI STATISTICS (idle landing)
  // =========================================================

  const schemaTables = schemaData?.tables || {};

  const schemaTableCount = Object.keys(schemaTables).length;

  const tableCountLabel =
    schemaTableCount > 0
      ? `${schemaTableCount} table${schemaTableCount === 1 ? "" : "s"} discovered`
      : "Schema not analyzed yet";

  const allUserSessions = useFilteredHistory(fetchedHistory, currentUser);

  const kpiStats = [
    {
      label: "Data Sources",
      value: isConnected ? 1 : 0,
      icon: "◈",
      support: (
        <span>
          {isConnected
            ? `${selectedSourceType === "csv" || selectedSourceType === "pdf" ? "File" : "Database"} connected`
            : "No source connected"}
        </span>
      ),
    },
    {
      label: "Tables",
      value: schemaTableCount,
      icon: "▦",
      support: (
        <span>
          {isConnected
            ? tableCountLabel
            : "Connect a source to discover tables"}
        </span>
      ),
    },
    {
      label: "Analyses",
      value: allUserSessions.length,
      icon: "✦",
      support: (
        <span>
          {allUserSessions.length === 0
            ? "No analyses yet"
            : "Completed by ARIA"}
        </span>
      ),
    },
    {
      label: "Saved Reports",
      value: allUserSessions.filter((session) => session.savedReport === true)
        .length,
      icon: "❒",
      support: (
        <span>
          {allUserSessions.filter((session) => session.savedReport === true)
            .length === 0
            ? "Nothing saved yet"
            : "Ready to review"}
        </span>
      ),
    },
  ];

  const maybeSubmitQuickAsk = () => {
    const text = String(quickAskValue || "").trim();

    if (text === "") {
      return;
    }

    if (typeof onQuickAsk === "function") {
      onQuickAsk(text);
    }
  };

  // =========================================================
  // CONNECTION / GOAL STATES
  // =========================================================

  const isConnected = connectionStatus === "connected";

  const isGoalRunning = goalStatus === "running";

  const isGoalSuccess = goalStatus === "success";

  const isGoalFailed = goalStatus === "failed";

  // =========================================================
  // INSIGHT AGENT STATES
  // =========================================================

  const isInsightRunning = insightStatus === "running";

  const isInsightSuccess = insightStatus === "success";

  const isInsightFailed = insightStatus === "failed";

  // =========================================================
  // CONNECTED SOURCE NAME
  // =========================================================

  const getConnectedSourceName = () => {
    if (!isConnected) {
      return "No data source connected";
    }

    if (selectedSourceType === "csv" || selectedSourceType === "pdf") {
      return selectedFile?.name || "Uploaded file";
    }

    if (selectedSourceType === "postgresql" || selectedSourceType === "mysql") {
      return dbName || "Connected database";
    }

    return "Connected source";
  };

  // =========================================================
  // NUMBER / CURRENCY FORMATTER
  // =========================================================

  const formatNumber = (value, key = "") => {
    if (typeof value !== "number") {
      return value;
    }

    const normalizedKey = key.toLowerCase();

    const isMoney =
      normalizedKey.includes("sales") ||
      normalizedKey.includes("revenue") ||
      normalizedKey.includes("amount") ||
      normalizedKey.includes("price");

    if (isMoney) {
      return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        maximumFractionDigits: 0,
      }).format(value);
    }

    return new Intl.NumberFormat("en-US").format(value);
  };

  // =========================================================
  // CHART VALUE FORMATTER
  // =========================================================

  const chartValueFormatter = (value) => {
    if (typeof value !== "number") {
      return value;
    }

    return new Intl.NumberFormat("en-US", {
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(value);
  };

  // =========================================================
  // TOOLTIP FORMATTER
  // =========================================================

  const tooltipFormatter = (value, name) => {
    if (typeof value !== "number") {
      return [value, name];
    }

    const normalizedName = String(name || "").toLowerCase();

    const isMoney =
      normalizedName.includes("sales") ||
      normalizedName.includes("revenue") ||
      normalizedName.includes("amount") ||
      normalizedName.includes("price");

    if (isMoney) {
      return [
        new Intl.NumberFormat("en-US", {
          style: "currency",
          currency: "USD",
          maximumFractionDigits: 0,
        }).format(value),
        name,
      ];
    }

    return [new Intl.NumberFormat("en-US").format(value), name];
  };

  // =========================================================
  // PIE / DONUT COLORS
  // =========================================================

  const pieColors = [
    "#2563eb",
    "#7c3aed",
    "#0891b2",
    "#059669",
    "#d97706",
    "#dc2626",
    "#4f46e5",
    "#0f766e",
  ];

  // =========================================================
  // CHART TYPE LABEL
  // =========================================================

  const getChartTypeLabel = (type) => {
    if (type === "line") {
      return "Line Chart";
    }

    if (type === "bar") {
      return "Bar Chart";
    }

    if (type === "horizontal-bar") {
      return "Horizontal Bar";
    }

    if (type === "area") {
      return "Area Chart";
    }

    if (type === "pie") {
      return "Pie Chart";
    }

    if (type === "donut") {
      return "Donut Chart";
    }

    if (type === "scatter") {
      return "Scatter Plot";
    }

    return "Visualization";
  };

  // =========================================================
  // AXIS LABEL FORMATTER
  // =========================================================

  const getAxisLabel = (customLabel, dataKey) => {
    if (customLabel) {
      return customLabel;
    }

    if (!dataKey) {
      return "";
    }

    return dataKey
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/_/g, " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase());
  };

  // =========================================================
  // DYNAMIC CHART ENGINE
  // =========================================================

  const renderChart = (chart) => {
    if (!chart || !Array.isArray(chart.data) || chart.data.length === 0) {
      return null;
    }

    // =======================================================
    // LINE CHART
    // =======================================================

    if (chart.type === "line") {
      return (
        <ResponsiveContainer width="100%" height={340}>
          <LineChart
            data={chart.data}
            margin={{
              top: 15,
              right: 25,
              left: 30,
              bottom: 40,
            }}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />

            <XAxis
              dataKey={chart.xKey}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.xLabel, chart.xKey),
                position: "insideBottom",
                offset: -20,
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <YAxis
              tickFormatter={chartValueFormatter}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.yLabel, chart.yKey),
                angle: -90,
                position: "insideLeft",
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <Tooltip formatter={tooltipFormatter} />

            <Line
              type="monotone"
              dataKey={chart.yKey}
              name={chart.yLabel || chart.yKey}
              stroke="#2563eb"
              strokeWidth={3}
              dot={{
                r: 4,
              }}
              activeDot={{
                r: 6,
              }}
            />
          </LineChart>
        </ResponsiveContainer>
      );
    }

    // =======================================================
    // BAR CHART
    // =======================================================

    if (chart.type === "bar") {
      return (
        <ResponsiveContainer width="100%" height={380}>
          <BarChart
            data={chart.data}
            margin={{
              top: 15,
              right: 25,
              left: 10,
              bottom: 80,
            }}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />

            <XAxis
              dataKey={chart.xKey}
              angle={-30}
              textAnchor="end"
              interval={0}
              height={100}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.xLabel, chart.xKey),
                position: "insideBottom",
                offset: -65,
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <YAxis
              tickFormatter={chartValueFormatter}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.yLabel, chart.yKey),
                angle: -90,
                position: "insideLeft",
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <Tooltip formatter={tooltipFormatter} />

            <Bar
              dataKey={chart.yKey}
              name={chart.yLabel || chart.yKey}
              fill="#2563eb"
              radius={[6, 6, 0, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      );
    }

    // =======================================================
    // HORIZONTAL BAR
    // =======================================================

    if (chart.type === "horizontal-bar") {
      return (
        <ResponsiveContainer width="100%" height={430}>
          <BarChart
            layout="vertical"
            data={chart.data}
            margin={{
              top: 15,
              right: 30,
              left: 85,
              bottom: 30,
            }}
          >
            <CartesianGrid strokeDasharray="3 3" horizontal={false} />

            <XAxis
              type="number"
              tickFormatter={chartValueFormatter}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.xLabel, chart.yKey),
                position: "insideBottom",
                offset: -10,
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <YAxis
              type="category"
              dataKey={chart.xKey}
              width={170}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.yLabel, chart.xKey),
                angle: -90,
                position: "insideLeft",
                offset: -65,
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                  textAnchor: "middle",
                },
              }}
            />

            <Tooltip formatter={tooltipFormatter} />

            <Bar
              dataKey={chart.yKey}
              name={chart.xLabel || chart.yLabel || chart.yKey}
              fill="#2563eb"
              radius={[0, 6, 6, 0]}
            />
          </BarChart>
        </ResponsiveContainer>
      );
    }

    // =======================================================
    // AREA CHART
    // =======================================================

    if (chart.type === "area") {
      return (
        <ResponsiveContainer width="100%" height={340}>
          <AreaChart
            data={chart.data}
            margin={{
              top: 15,
              right: 25,
              left: 30,
              bottom: 40,
            }}
          >
            <CartesianGrid strokeDasharray="3 3" vertical={false} />

            <XAxis
              dataKey={chart.xKey}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.xLabel, chart.xKey),
                position: "insideBottom",
                offset: -20,
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <YAxis
              tickFormatter={chartValueFormatter}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.yLabel, chart.yKey),
                angle: -90,
                position: "insideLeft",
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <Tooltip formatter={tooltipFormatter} />

            <Area
              type="monotone"
              dataKey={chart.yKey}
              name={chart.yLabel || chart.yKey}
              stroke="#2563eb"
              fill="#bfdbfe"
              strokeWidth={3}
            />
          </AreaChart>
        </ResponsiveContainer>
      );
    }

    // =======================================================
    // PIE CHART
    // =======================================================

    if (chart.type === "pie") {
      const nameKey = chart.nameKey || chart.xKey;

      const valueKey = chart.valueKey || chart.yKey;

      return (
        <ResponsiveContainer width="100%" height={380}>
          <PieChart>
            <Tooltip
              formatter={(value) => [
                formatNumber(value, valueKey),
                chart.yLabel || valueKey,
              ]}
            />

            <Pie
              data={chart.data}
              dataKey={valueKey}
              nameKey={nameKey}
              cx="50%"
              cy="50%"
              outerRadius={125}
              label={({ name, percent }) =>
                `${name}: ${Math.round((percent || 0) * 100)}%`
              }
            >
              {chart.data.map((entry, index) => (
                <Cell
                  key={`pie-${entry[nameKey]}-${index}`}
                  fill={pieColors[index % pieColors.length]}
                />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      );
    }

    // =======================================================
    // DONUT CHART
    // =======================================================

    if (chart.type === "donut") {
      const nameKey = chart.nameKey || chart.xKey;

      const valueKey = chart.valueKey || chart.yKey;

      const totalValue = chart.data.reduce(
        (total, item) => total + Number(item[valueKey] || 0),
        0,
      );

      return (
        <div
          style={{
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: "28px",
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              flex: "1 1 330px",
              minWidth: "280px",
              height: "360px",
            }}
          >
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Tooltip
                  formatter={(value) => [formatNumber(value, "sales"), "Sales"]}
                />

                <Pie
                  data={chart.data}
                  dataKey={valueKey}
                  nameKey={nameKey}
                  cx="50%"
                  cy="50%"
                  innerRadius={78}
                  outerRadius={125}
                  paddingAngle={2}
                  label={false}
                  labelLine={false}
                >
                  {chart.data.map((entry, index) => (
                    <Cell
                      key={`donut-${entry[nameKey]}-${index}`}
                      fill={pieColors[index % pieColors.length]}
                    />
                  ))}
                </Pie>
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div
            style={{
              flex: "1 1 240px",
              minWidth: "220px",
              maxWidth: "310px",
              display: "flex",
              flexDirection: "column",
              gap: "13px",
            }}
          >
            {chart.data.map((item, index) => {
              const value = Number(item[valueKey] || 0);

              const percentage =
                totalValue > 0 ? Math.round((value / totalValue) * 100) : 0;

              return (
                <div
                  key={`legend-${item[nameKey]}-${index}`}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: "14px",
                    paddingBottom: "10px",
                    borderBottom:
                      index === chart.data.length - 1
                        ? "none"
                        : "1px solid #edf0f5",
                  }}
                >
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "9px",
                      minWidth: 0,
                    }}
                  >
                    <span
                      style={{
                        width: "9px",
                        height: "9px",
                        flexShrink: 0,
                        borderRadius: "50%",
                        background: pieColors[index % pieColors.length],
                      }}
                    />

                    <span
                      style={{
                        color: "#334155",
                        fontSize: "12px",
                        fontWeight: 600,
                      }}
                    >
                      {item[nameKey]}
                    </span>
                  </div>

                  <div
                    style={{
                      textAlign: "right",
                      flexShrink: 0,
                    }}
                  >
                    <strong
                      style={{
                        display: "block",
                        color: "#17233c",
                        fontSize: "12px",
                      }}
                    >
                      {percentage}%
                    </strong>

                    <span
                      style={{
                        color: "#64748b",
                        fontSize: "11px",
                      }}
                    >
                      {formatNumber(value, "sales")}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      );
    }

    // =======================================================
    // SCATTER CHART
    // =======================================================

    if (chart.type === "scatter") {
      return (
        <ResponsiveContainer width="100%" height={360}>
          <ScatterChart
            margin={{
              top: 15,
              right: 25,
              left: 10,
              bottom: 25,
            }}
          >
            <CartesianGrid strokeDasharray="3 3" />

            <XAxis
              type="number"
              dataKey={chart.xKey}
              name={chart.xLabel || chart.xKey}
              tickFormatter={chartValueFormatter}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.xLabel, chart.xKey),
                position: "insideBottom",
                offset: -12,
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <YAxis
              type="number"
              dataKey={chart.yKey}
              name={chart.yLabel || chart.yKey}
              tickFormatter={chartValueFormatter}
              tickLine={false}
              axisLine={false}
              label={{
                value: getAxisLabel(chart.yLabel, chart.yKey),
                angle: -90,
                position: "insideLeft",
                style: {
                  fill: "#64748b",
                  fontSize: 12,
                  fontWeight: 600,
                },
              }}
            />

            <Tooltip
              cursor={{
                strokeDasharray: "3 3",
              }}
              formatter={tooltipFormatter}
            />

            <Scatter data={chart.data} fill="#2563eb" />
          </ScatterChart>
        </ResponsiveContainer>
      );
    }

    return (
      <div className="chart-unavailable">
        ARIA received an unsupported chart type.
      </div>
    );
  };

  // =========================================================
  // MULTI-CHART NORMALIZATION
  // =========================================================

  const analyticsCharts = Array.isArray(analysisResult?.charts)
    ? analysisResult.charts
    : analysisResult?.chart
      ? [analysisResult.chart]
      : [];
  // =========================================================
  // DAY 8 - SUBMIT USER FEEDBACK
  // =========================================================
  const requiresFeedbackComment =
    overallUseful === false || reactionRating <= 2 || overallRating <= 2;

  const handleBasicFeedbackSubmit = () => {
    if (
      reactionRating === 0 ||
      overallUseful === null ||
      overallRating === 0 ||
      (requiresFeedbackComment && feedbackCorrection.trim() === "")
    ) {
      return;
    }

    handleFeedbackSubmit({
      overallUseful,
      overallRating,
      reactionRating,
      insightFeedback,
      anomalyFeedback,
      hypothesisFeedback,
      chartFeedback,
      recommendationFeedback,
      bestHypothesis,
      correction: feedbackCorrection.trim(),
    });
  };

  return (
    <div className="dashboard-page">
      {/* =====================================================
          PAGE HEADER
      ====================================================== */}

      <div className="page-header">
        <div>
          <span className="dashboard-eyebrow">{greetingName}</span>

          <h1>Analytics Dashboard</h1>

          <p>Here&apos;s what&apos;s happening across your data.</p>
        </div>

        <div className="dashboard-source-status">
          <span className="source-status-label">Data Source</span>

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              gap: "12px",
            }}
          >
            <strong>{getConnectedSourceName()}</strong>

            <span
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                flexShrink: 0,
                fontSize: "11px",
                fontWeight: 700,
                color:
                  connectionStatus === "connected"
                    ? "#15803d"
                    : connectionStatus === "connecting"
                      ? "#b45309"
                      : connectionStatus === "failed"
                        ? "#dc2626"
                        : "#64748b",
              }}
            >
              <span
                style={{
                  width: "7px",
                  height: "7px",
                  borderRadius: "50%",
                  background:
                    connectionStatus === "connected"
                      ? "#22c55e"
                      : connectionStatus === "connecting"
                        ? "#f59e0b"
                        : connectionStatus === "failed"
                          ? "#ef4444"
                          : "#94a3b8",
                }}
              />

              {connectionStatus === "connected"
                ? "Connected"
                : connectionStatus === "connecting"
                  ? "Connecting"
                  : connectionStatus === "failed"
                    ? "Failed"
                    : "Not connected"}
            </span>
          </div>
        </div>
      </div>

      {/* =====================================================
          DASHBOARD LANDING (idle command center)
      ====================================================== */}

      {!submittedQuestion && goalStatus === "idle" && (
        <div className="dashboard-landing">
          <div className="dashboard-kpi-grid">
            {kpiStats.map((stat, index) => (
              <div
                className="dashboard-kpi-card"
                key={stat.label}
                style={{ animationDelay: `${index * 70}ms` }}
              >
                <div className="dashboard-kpi-top">
                  <span className="dashboard-kpi-label">{stat.label}</span>

                  <span className="dashboard-kpi-icon" aria-hidden="true">
                    {stat.icon}
                  </span>
                </div>

                <AnimatedKpiValue value={stat.value} />

                <span className="dashboard-kpi-support">{stat.support}</span>
              </div>
            ))}
          </div>

          <section className="dashboard-quick-ask section-card">
            <div className="dashboard-quick-ask-heading">
              <span className="dashboard-eyebrow">✦ Ask ARIA</span>

              <h3>What do you want to understand?</h3>

              <p>
                Ask a business question in plain language and ARIA will build the
                analysis for you.
              </p>
            </div>

            <div className="ask-input-wrapper">
              <input
                type="text"
                value={quickAskValue}
                onChange={(event) => setQuickAskValue(event.target.value)}
                placeholder={
                  isConnected
                    ? "Example: Show me monthly sales trends"
                    : "Example: Summarize my top customers"
                }
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    maybeSubmitQuickAsk();
                  }
                }}
              />

              <button
                type="button"
                className="primary-button"
                onClick={maybeSubmitQuickAsk}
              >
                Ask ARIA →
              </button>
            </div>

            {!isConnected && (
              <button
                type="button"
                className="dashboard-connect-link"
                onClick={() => onNavigate && onNavigate("dataSource")}
              >
                No data source connected yet · Connect one to get started
              </button>
            )}
          </section>

          <div className="dashboard-landing-grid">
            <section className="dashboard-panel section-card">
              <div className="dashboard-panel-heading">
                <div>
                  <span className="dashboard-eyebrow">Recent Activity</span>

                  <h3>Latest analyses</h3>
                </div>

                <button
                  type="button"
                  className="dashboard-view-all"
                  onClick={() => onNavigate && onNavigate("history")}
                >
                  View all
                </button>
              </div>

              {recentSessions.length > 0 ? (
                <ul className="dashboard-recent-list">
                  {recentSessions.map((session) => (
                    <li key={session.id}>
                      <span className="dashboard-recent-icon" aria-hidden="true">
                        ✦
                      </span>

                      <div className="dashboard-recent-content">
                        <strong>{session.question}</strong>

                        <span>
                          {session.source?.name || "Data source"} ·{" "}
                          {formatRecentDate(session.createdAt)}
                        </span>
                      </div>

                      <button
                        type="button"
                        aria-label="Open analysis"
                        onClick={() => onNavigate && onNavigate("history")}
                      >
                        →
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="empty-state">
                  <span className="empty-state-icon" aria-hidden="true">
                    ✦
                  </span>

                  <h3>Your analysis workspace</h3>

                  <p>
                    Completed ARIA analyses will appear here so you can revisit
                    previous questions, dashboards, and insights.
                  </p>

                  <div className="empty-state-actions">
                    <button
                      type="button"
                      className="primary-button"
                      onClick={maybeSubmitQuickAsk}
                    >
                      Ask ARIA →
                    </button>
                  </div>
                </div>
              )}
            </section>

            <section className="dashboard-panel section-card">
              <div className="dashboard-panel-heading">
                <div>
                  <span className="dashboard-eyebrow">Data Status</span>

                  <h3>Connected source</h3>
                </div>
              </div>

              <div className="dashboard-status-row">
                <span
                  className={`dashboard-status-indicator ${
                    connectionStatus === "connected" ? "connected" : ""
                  }`}
                />

                <div>
                  <strong>{getConnectedSourceName()}</strong>

                  <span>
                    {connectionStatus === "connected"
                      ? `${selectedSourceType === "csv" || selectedSourceType === "pdf" ? "File source" : "Database"} ready for analysis`
                      : connectionStatus === "connecting"
                        ? "Connecting..."
                        : connectionStatus === "failed"
                          ? "Connection failed"
                          : "No database connected yet"}
                  </span>
                </div>
              </div>

              <div className="dashboard-status-actions">
                <button
                  type="button"
                  className="copilot-action-btn"
                  onClick={() => onNavigate && onNavigate("schema")}
                >
                  View schema
                </button>

                <button
                  type="button"
                  className="copilot-action-btn"
                  onClick={() =>
                    onNavigate && onNavigate(connectionStatus === "connected" ? "dataSource" : "dataSource")
                  }
                >
                  Manage sources
                </button>
              </div>
            </section>
          </div>
        </div>
      )}

      {/* =====================================================
          GOAL AGENT RUNNING / PROCESSING CHECKLIST
      ====================================================== */}

      {isGoalRunning && (
        <section className="ai-processing-card section-card">
          <div className="ai-processing-head">
            <div className="ai-processing-brand" aria-hidden="true">
              ✦
            </div>

            <div className="ai-processing-head-text">
              <span>ARIA</span>

              <strong>Analyzing your data</strong>
            </div>
          </div>

          <div className="ai-processing-steps">
            <div className="ai-processing-step running">
              <span className="step-state">◌</span>

              Understanding your question
            </div>

            <div className="ai-processing-step pending">
              <span className="step-state">○</span>

              Identifying relevant data
            </div>

            <div className="ai-processing-step pending">
              <span className="step-state">○</span>

              Running the analysis
            </div>

            <div className="ai-processing-step pending">
              <span className="step-state">○</span>

              Preparing insights
            </div>
          </div>
        </section>
      )}

      {/* =====================================================
          GOAL AGENT ERROR
      ====================================================== */}

      {isGoalFailed && (
        <section className="section-card">
          <div className="connection-error">
            <strong>ARIA couldn&apos;t complete this request</strong>

            <p>
              Something went wrong while analyzing your question. You can try
              again in a moment.
            </p>

            {goalError && (
              <p className="error-detail">Details: {goalError}</p>
            )}

            <div className="error-actions">
              <button
                type="button"
                className="primary-button"
                onClick={() => onRetry && onRetry()}
              >
                Try again
              </button>
            </div>
          </div>
        </section>
      )}

      {/* =====================================================
          QUESTION RECEIVED
      ====================================================== */}

      {submittedQuestion && (
        <section className="section-card">
          <div className="submitted-question">
            <span>Question received</span>

            <strong>{submittedQuestion}</strong>
          </div>
        </section>
      )}

      {/* =====================================================
          DID YOU MEAN
      ====================================================== */}

      {isGoalSuccess && goalResult?.correctedQuestion && (
        <section className="goal-correction-card">
          <div>
            <span>Did you mean?</span>

            <strong>{goalResult.correctedQuestion}</strong>
          </div>

          <button
            type="button"
            onClick={() => handleSuggestionSelect(goalResult.correctedQuestion)}
          >
            Use this question
          </button>
        </section>
      )}

      {/* =====================================================
          GOAL AGENT RESULT
      ====================================================== */}

      {isGoalSuccess && goalResult && (
        <section className="section-card">
          <div className="goal-agent-header">
            <div>
              <span className="goal-agent-label">Goal Agent</span>

              <h3>Business Goal Understood</h3>
            </div>

            <span className="goal-status-badge">Ready</span>
          </div>

          <div className="goal-result-section">
            <div className="goal-section-title">Interpreted Goal</div>

            <div className="goal-interpretation">
              <p>{goalResult.interpretedGoal}</p>

              <span>{goalResult.goalType}</span>
            </div>
          </div>

          {goalResult.clarificationRequired && (
            <div className="goal-clarification">
              <strong>ARIA needs more information</strong>

              <p>{goalResult.clarificationMessage}</p>
            </div>
          )}

          {goalResult.relevantTables?.length > 0 && (
            <div className="goal-result-section">
              <div className="goal-section-title">Relevant Tables</div>

              <div className="goal-table-chips">
                {goalResult.relevantTables.map((table) => (
                  <span key={table} className="goal-table-chip">
                    {table}
                  </span>
                ))}
              </div>
            </div>
          )}

          {goalResult.joinPlan?.length > 0 && (
            <div className="goal-result-section">
              <div className="goal-section-title">Join Plan</div>

              <div className="goal-step-list">
                {goalResult.joinPlan.map((step, index) => (
                  <div className="goal-step-item" key={`${step}-${index}`}>
                    <span>{index + 1}</span>

                    <p>{step}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {goalResult.generatedSql && (
            <div className="goal-result-section">
              <div className="goal-section-title">Generated SQL</div>

              <pre className="goal-sql-block">
                <code>{goalResult.generatedSql}</code>
              </pre>
            </div>
          )}

          {goalResult.preprocessing?.length > 0 && (
            <div className="goal-result-section">
              <div className="goal-section-title">Data Preparation</div>

              <div className="goal-step-list">
                {goalResult.preprocessing.map((step, index) => (
                  <div className="goal-step-item" key={`${step}-${index}`}>
                    <span>{index + 1}</span>

                    <p>{step}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {goalResult.processedDataSummary && (
            <div className="goal-processing-summary">
              <div>
                <span>Processed Rows</span>

                <strong>{goalResult.processedDataSummary.rowCount}</strong>
              </div>

              <div>
                <span>Output Columns</span>

                <strong>
                  {goalResult.processedDataSummary.columns?.length || 0}
                </strong>
              </div>

              <div>
                <span>Next Agent</span>

                <strong>{goalResult.nextAgent}</strong>
              </div>
            </div>
          )}

          {!goalResult.processedDataSummary &&
            goalResult.nextAgent &&
            !goalResult.clarificationRequired && (
              <div className="goal-next-agent">
                Next: <strong>{goalResult.nextAgent}</strong>
              </div>
            )}
        </section>
      )}

      {/* =====================================================
          DAY 6 ANALYTICS RESULT
      ====================================================== */}

      {analysisResult && (
        <section className="analytics-results">
          <div className="analytics-result-header">
            <div>
              <span className="analytics-result-label">Analytics Result</span>

              <h2>Your Data at a Glance</h2>

              <p>
                ARIA prepared the processed data for visualization and further
                Insight Agent analysis.
              </p>
            </div>

            <div className="analytics-result-actions">
              {currentHistorySessionId &&
                typeof handleSaveReport === "function" && (
                  <button
                    type="button"
                    className="insight-retry-button"
                    onClick={() => {
                      handleSaveReport(currentHistorySessionId);

                      setLocalReportSaved(true);
                    }}
                    disabled={localReportSaved}
                  >
                    {localReportSaved ? "Saved Report" : "Save Report"}
                  </button>
                )}

              <span className="analytics-ready-badge">Data Ready</span>
            </div>
          </div>

          {analysisResult.kpis?.length > 0 && (
            <div className="analytics-kpi-grid">
              {analysisResult.kpis.map((kpi, index) => (
                <div
                  className="analytics-kpi-card"
                  key={`${kpi.label}-${index}`}
                >
                  <span className="analytics-kpi-label">{kpi.label}</span>

                  <strong className="analytics-kpi-value">{kpi.value}</strong>
                </div>
              ))}
            </div>
          )}

          {analyticsCharts.length > 0 && (
            <div className="analytics-visualizations-section">
              <div className="analytics-visualizations-heading">
                <div>
                  <span>Visual Analytics</span>

                  <h2>Generated Dashboard</h2>

                  <p>
                    ARIA selected the visualizations that best represent this
                    analysis.
                  </p>
                </div>

                <div className="visualization-count-badge">
                  {analyticsCharts.length}{" "}
                  {analyticsCharts.length === 1
                    ? "visualization"
                    : "visualizations"}
                </div>
              </div>

              <div
                className={
                  analyticsCharts.length === 1
                    ? "analytics-chart-grid single-chart"
                    : "analytics-chart-grid"
                }
              >
                {analyticsCharts.map((chart, index) => (
                  <div
                    className="analytics-chart-card"
                    key={`${chart.title}-${index}`}
                  >
                    <div className="analytics-card-heading">
                      <div>
                        <span>Visualization {index + 1}</span>

                        <h3>{chart.title}</h3>
                      </div>

                      <div className="chart-type-badge">
                        {getChartTypeLabel(chart.type)}
                      </div>
                    </div>

                    <div className="analytics-chart-wrapper">
                      {renderChart(chart)}
                    </div>
                    {isInsightSuccess && (
                      <div className="individual-feedback chart-feedback-block">
                        <span className="individual-feedback-question">
                          Was this visualization useful?
                        </span>

                        <div className="individual-feedback-actions">
                          <button
                            type="button"
                            className={
                              chartFeedback[index] === "useful"
                                ? "individual-feedback-button active"
                                : "individual-feedback-button"
                            }
                            onClick={() =>
                              setChartFeedback((current) => ({
                                ...current,
                                [index]: "useful",
                              }))
                            }
                          >
                            Useful
                          </button>

                          <button
                            type="button"
                            className={
                              chartFeedback[index] === "not-useful"
                                ? "individual-feedback-button active negative"
                                : "individual-feedback-button"
                            }
                            onClick={() =>
                              setChartFeedback((current) => ({
                                ...current,
                                [index]: "not-useful",
                              }))
                            }
                          >
                            Not Useful
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {analysisResult.table &&
            analysisResult.table.columns?.length > 0 &&
            analysisResult.table.rows?.length > 0 && (
              <div className="analytics-table-card">
                <div className="analytics-card-heading">
                  <div>
                    <span>Processed Data</span>

                    <h3>Result Table</h3>
                  </div>

                  <div className="table-row-count">
                    {analysisResult.table.rows.length} rows
                  </div>
                </div>

                <div className="analytics-table-wrapper">
                  <table className="analytics-data-table">
                    <thead>
                      <tr>
                        {analysisResult.table.columns.map((column) => (
                          <th key={column.key}>{column.label}</th>
                        ))}
                      </tr>
                    </thead>

                    <tbody>
                      {analysisResult.table.rows.map((row, rowIndex) => (
                        <tr key={rowIndex}>
                          {analysisResult.table.columns.map((column) => (
                            <td key={column.key}>
                              {formatNumber(row[column.key], column.key)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}

          <div className="analytics-next-step">
            <div>
              <span>Pipeline Status</span>

              <strong>Processed data is ready for the Insight Agent</strong>
            </div>

            <div className="analytics-next-arrow">→</div>
          </div>
        </section>
      )}

      {/* =====================================================
          DAY 7 - INSIGHT AGENT
      ====================================================== */}

      {(isInsightRunning || isInsightSuccess || isInsightFailed) && (
        <section className="insight-agent-section">
          {/* ===============================================
              RUNNING
          ================================================ */}

          {isInsightRunning && (
            <div className="insight-processing-card">
              <div className="insight-processing-icon">
                <div className="insight-spinner" />
              </div>

              <div className="insight-processing-content">
                <span className="insight-agent-label">Insight Agent</span>

                <h2>Insight Agent is analyzing the results...</h2>

                <p>
                  ARIA is examining the processed data and visual analytics to
                  identify the business signals that matter most.
                </p>

                <div className="insight-processing-list">
                  <span>Patterns and trends</span>

                  <span>Anomalies</span>

                  <span>Ranked hypotheses</span>

                  <span>Business opportunities</span>
                </div>
              </div>
            </div>
          )}

          {/* ===============================================
              ERROR
          ================================================ */}

          {isInsightFailed && (
            <div className="insight-error-card">
              <div>
                <span className="insight-agent-label">Insight Agent</span>

                <h3>Insight analysis could not be completed</h3>

                <p>
                  {insightError ||
                    "ARIA could not generate insight analysis from the processed result."}
                </p>

                <button
                  type="button"
                  className="insight-retry-button"
                  onClick={handleInsightRetry}
                >
                  Retry Insight Analysis
                </button>
              </div>

              <span className="insight-failed-badge">Failed</span>
            </div>
          )}

          {/* ===============================================
              SUCCESS
          ================================================ */}

          {isInsightSuccess && insightResult && (
            <>
              <div className="insight-agent-header">
                <div>
                  <span className="insight-agent-label">Insight Agent</span>

                  <h2>Business Insights Ready</h2>

                  <p>
                    ARIA analyzed the dashboard results and identified the most
                    important findings for this business question.
                  </p>
                </div>

                <span className="insight-ready-badge">Analysis Ready</span>
              </div>

              {/* =========================================
                    KEY INSIGHTS
                ========================================== */}

              {insightResult.keyInsights?.length > 0 && (
                <div className="insight-key-section">
                  <div className="insight-section-heading">
                    <div>
                      <span>Key Insights</span>

                      <h2>What ARIA Found</h2>

                      <p>
                        The most important business findings detected in the
                        current analysis.
                      </p>
                    </div>

                    <div className="insight-count-badge">
                      {insightResult.keyInsights.length}{" "}
                      {insightResult.keyInsights.length === 1
                        ? "insight"
                        : "insights"}
                    </div>
                  </div>

                  <div className="insight-key-grid">
                    {insightResult.keyInsights.map((insight, index) => (
                      <article
                        className="insight-key-card"
                        key={`${insight.title}-${index}`}
                      >
                        <div className="insight-card-top">
                          <span className="insight-number">
                            {String(index + 1).padStart(2, "0")}
                          </span>

                          <span
                            className={`insight-impact-badge ${
                              insight.impact || "medium"
                            }`}
                          >
                            {insight.impact
                              ? `${insight.impact} impact`
                              : "Insight"}
                          </span>
                        </div>

                        <h3>{insight.title}</h3>

                        <p>{insight.description}</p>
                        <div className="individual-feedback">
                          <span className="individual-feedback-question">
                            Was this insight correct?
                          </span>

                          <div className="individual-feedback-actions">
                            <button
                              type="button"
                              className={
                                insightFeedback[index] === "correct"
                                  ? "individual-feedback-button active"
                                  : "individual-feedback-button"
                              }
                              onClick={() =>
                                setInsightFeedback((current) => ({
                                  ...current,
                                  [index]: "correct",
                                }))
                              }
                            >
                              Correct
                            </button>

                            <button
                              type="button"
                              className={
                                insightFeedback[index] === "incorrect"
                                  ? "individual-feedback-button active negative"
                                  : "individual-feedback-button"
                              }
                              onClick={() =>
                                setInsightFeedback((current) => ({
                                  ...current,
                                  [index]: "incorrect",
                                }))
                              }
                            >
                              Incorrect
                            </button>
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              )}

              {/* =========================================
                    TRENDS & PATTERNS
                ========================================== */}

              {insightResult.trends?.length > 0 && (
                <div className="insight-trends-section">
                  <div className="insight-section-heading">
                    <div>
                      <span>Trends & Patterns</span>

                      <h2>How the Data Is Moving</h2>

                      <p>
                        ARIA identified the strongest directional patterns in
                        the current analysis.
                      </p>
                    </div>

                    <div className="insight-count-badge">
                      {insightResult.trends.length}{" "}
                      {insightResult.trends.length === 1
                        ? "pattern"
                        : "patterns"}
                    </div>
                  </div>

                  <div className="insight-trend-grid">
                    {insightResult.trends.map((trend, index) => {
                      const direction = trend.direction || "mixed";

                      const directionSymbol =
                        direction === "up"
                          ? "↑"
                          : direction === "down"
                            ? "↓"
                            : "↔";

                      const directionLabel =
                        direction === "up"
                          ? "Upward"
                          : direction === "down"
                            ? "Downward"
                            : "Mixed";

                      return (
                        <article
                          className={`insight-trend-card ${direction}`}
                          key={`${trend.title}-${index}`}
                        >
                          <div className="insight-trend-icon">
                            {directionSymbol}
                          </div>

                          <div className="insight-trend-content">
                            <div className="insight-trend-top">
                              <span className="insight-number">
                                {String(index + 1).padStart(2, "0")}
                              </span>

                              <span
                                className={`insight-direction-badge ${direction}`}
                              >
                                {directionLabel}
                              </span>
                            </div>

                            <h3>{trend.title}</h3>

                            <p>{trend.description}</p>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* =========================================
                    ANOMALY DETECTION
                ========================================== */}

              {insightResult.anomalies?.length > 0 && (
                <div className="insight-anomalies-section">
                  <div className="insight-section-heading">
                    <div>
                      <span>Anomaly Detection</span>

                      <h2>Unusual Signals Detected</h2>

                      <p>
                        ARIA highlighted results that break the normal pattern
                        and may require closer business review.
                      </p>
                    </div>

                    <div className="insight-anomaly-count-badge">
                      {insightResult.anomalies.length}{" "}
                      {insightResult.anomalies.length === 1
                        ? "anomaly"
                        : "anomalies"}
                    </div>
                  </div>

                  <div className="insight-anomaly-list">
                    {insightResult.anomalies.map((anomaly, index) => {
                      const severity = anomaly.severity || "medium";

                      return (
                        <article
                          className={`insight-anomaly-card ${severity}`}
                          key={`${anomaly.title}-${index}`}
                        >
                          <div className="insight-anomaly-icon">!</div>

                          <div className="insight-anomaly-content">
                            <div className="insight-anomaly-top">
                              <span className="insight-number">
                                {String(index + 1).padStart(2, "0")}
                              </span>

                              <span
                                className={`insight-severity-badge ${severity}`}
                              >
                                {severity} severity
                              </span>
                            </div>

                            <h3>{anomaly.title}</h3>

                            <p>{anomaly.description}</p>
                            <div className="individual-feedback">
                              <span className="individual-feedback-question">
                                Was this anomaly valid?
                              </span>

                              <div className="individual-feedback-actions">
                                <button
                                  type="button"
                                  className={
                                    anomalyFeedback[index] === "valid"
                                      ? "individual-feedback-button active"
                                      : "individual-feedback-button"
                                  }
                                  onClick={() =>
                                    setAnomalyFeedback((current) => ({
                                      ...current,
                                      [index]: "valid",
                                    }))
                                  }
                                >
                                  Valid Anomaly
                                </button>

                                <button
                                  type="button"
                                  className={
                                    anomalyFeedback[index] === "false-alarm"
                                      ? "individual-feedback-button active negative"
                                      : "individual-feedback-button"
                                  }
                                  onClick={() =>
                                    setAnomalyFeedback((current) => ({
                                      ...current,
                                      [index]: "false-alarm",
                                    }))
                                  }
                                >
                                  False Alarm
                                </button>
                              </div>
                            </div>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* =========================================
                    RANKED HYPOTHESES
                ========================================== */}

              {insightResult.hypotheses?.length > 0 && (
                <div className="insight-hypotheses-section">
                  <div className="insight-section-heading">
                    <div>
                      <span>Ranked Hypotheses</span>

                      <h2>Why This May Be Happening</h2>

                      <p>
                        ARIA ranked the most likely explanations for the
                        patterns detected in this analysis.
                      </p>
                    </div>

                    <div className="insight-count-badge">
                      {insightResult.hypotheses.length}{" "}
                      {insightResult.hypotheses.length === 1
                        ? "hypothesis"
                        : "hypotheses"}
                    </div>
                  </div>

                  <div className="insight-hypothesis-list">
                    {insightResult.hypotheses.map((hypothesis, index) => {
                      const confidence = Math.round(
                        Number(hypothesis.confidence || 0) * 100,
                      );

                      return (
                        <article
                          className="insight-hypothesis-card"
                          key={`${hypothesis.title}-${index}`}
                        >
                          <div className="insight-hypothesis-rank">
                            <span>Rank</span>

                            <strong>#{hypothesis.rank || index + 1}</strong>
                          </div>

                          <div className="insight-hypothesis-content">
                            <div className="insight-hypothesis-top">
                              <div>
                                <span className="insight-hypothesis-label">
                                  Possible Explanation
                                </span>

                                <h3>{hypothesis.title}</h3>
                              </div>

                              <div className="insight-confidence-badge">
                                <strong>{confidence}%</strong>

                                <span>confidence</span>
                              </div>
                            </div>

                            <p className="insight-hypothesis-description">
                              {hypothesis.description}
                            </p>

                            {hypothesis.evidence?.length > 0 && (
                              <div className="insight-evidence-section">
                                <span className="insight-evidence-title">
                                  Supporting Evidence
                                </span>

                                <div className="insight-evidence-list">
                                  {hypothesis.evidence.map(
                                    (evidence, evidenceIndex) => (
                                      <div
                                        className="insight-evidence-item"
                                        key={`${evidence}-${evidenceIndex}`}
                                      >
                                        <span className="insight-evidence-dot" />

                                        <p>{evidence}</p>
                                      </div>
                                    ),
                                  )}
                                </div>
                                <div className="individual-feedback">
                                  <span className="individual-feedback-question">
                                    How accurate is this hypothesis?
                                  </span>

                                  <div className="individual-feedback-actions">
                                    <button
                                      type="button"
                                      className={
                                        hypothesisFeedback[index] === "correct"
                                          ? "individual-feedback-button active"
                                          : "individual-feedback-button"
                                      }
                                      onClick={() =>
                                        setHypothesisFeedback((current) => ({
                                          ...current,
                                          [index]: "correct",
                                        }))
                                      }
                                    >
                                      Correct
                                    </button>

                                    <button
                                      type="button"
                                      className={
                                        hypothesisFeedback[index] ===
                                        "partially-correct"
                                          ? "individual-feedback-button active partial"
                                          : "individual-feedback-button"
                                      }
                                      onClick={() =>
                                        setHypothesisFeedback((current) => ({
                                          ...current,
                                          [index]: "partially-correct",
                                        }))
                                      }
                                    >
                                      Partially Correct
                                    </button>

                                    <button
                                      type="button"
                                      className={
                                        hypothesisFeedback[index] ===
                                        "incorrect"
                                          ? "individual-feedback-button active negative"
                                          : "individual-feedback-button"
                                      }
                                      onClick={() =>
                                        setHypothesisFeedback((current) => ({
                                          ...current,
                                          [index]: "incorrect",
                                        }))
                                      }
                                    >
                                      Incorrect
                                    </button>

                                    <button
                                      type="button"
                                      className={
                                        hypothesisFeedback[index] === "not-sure"
                                          ? "individual-feedback-button active unsure"
                                          : "individual-feedback-button"
                                      }
                                      onClick={() =>
                                        setHypothesisFeedback((current) => ({
                                          ...current,
                                          [index]: "not-sure",
                                        }))
                                      }
                                    >
                                      Not Sure
                                    </button>
                                  </div>
                                </div>
                              </div>
                            )}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* =========================================
                    BUSINESS RECOMMENDATIONS
                ========================================== */}

              {insightResult.recommendations?.length > 0 && (
                <div className="insight-recommendations-section">
                  <div className="insight-section-heading">
                    <div>
                      <span>Business Recommendations</span>

                      <h2>What ARIA Suggests Next</h2>

                      <p>
                        Recommended actions based on the patterns, anomalies,
                        and hypotheses identified in this analysis.
                      </p>
                    </div>

                    <div className="insight-recommendation-count-badge">
                      {insightResult.recommendations.length}{" "}
                      {insightResult.recommendations.length === 1
                        ? "action"
                        : "actions"}
                    </div>
                  </div>

                  <div className="insight-recommendation-grid">
                    {insightResult.recommendations.map(
                      (recommendation, index) => {
                        const priority = String(
                          recommendation.priority || "medium",
                        ).toLowerCase();

                        return (
                          <article
                            className={`insight-recommendation-card ${priority}`}
                            key={`${recommendation.title}-${index}`}
                          >
                            <div className="insight-recommendation-top">
                              <div className="insight-recommendation-number">
                                {String(index + 1).padStart(2, "0")}
                              </div>

                              <span
                                className={`insight-priority-badge ${priority}`}
                              >
                                {priority} priority
                              </span>
                            </div>

                            <div className="insight-recommendation-icon">→</div>

                            <h3>{recommendation.title}</h3>

                            <p>{recommendation.description}</p>
                            <div className="individual-feedback">
                              <span className="individual-feedback-question">
                                Was this recommendation actionable?
                              </span>

                              <div className="individual-feedback-actions">
                                <button
                                  type="button"
                                  className={
                                    recommendationFeedback[index] ===
                                    "actionable"
                                      ? "individual-feedback-button active"
                                      : "individual-feedback-button"
                                  }
                                  onClick={() =>
                                    setRecommendationFeedback((current) => ({
                                      ...current,
                                      [index]: "actionable",
                                    }))
                                  }
                                >
                                  Actionable
                                </button>

                                <button
                                  type="button"
                                  className={
                                    recommendationFeedback[index] ===
                                    "not-actionable"
                                      ? "individual-feedback-button active negative"
                                      : "individual-feedback-button"
                                  }
                                  onClick={() =>
                                    setRecommendationFeedback((current) => ({
                                      ...current,
                                      [index]: "not-actionable",
                                    }))
                                  }
                                >
                                  Not Actionable
                                </button>
                              </div>
                            </div>
                          </article>
                        );
                      },
                    )}
                  </div>
                </div>
              )}

              {/* =========================================
                    DAY 7 STEP 9 - PREDICTIONS
                ========================================== */}

              {insightResult.predictions?.length > 0 && (
                <div className="insight-predictions-section">
                  <div className="insight-section-heading">
                    <div>
                      <span>Predictions</span>

                      <h2>What May Happen Next</h2>

                      <p>
                        Forward-looking signals based on the trends and patterns
                        detected in the current analysis.
                      </p>
                    </div>

                    <div className="insight-prediction-count-badge">
                      {insightResult.predictions.length}{" "}
                      {insightResult.predictions.length === 1
                        ? "prediction"
                        : "predictions"}
                    </div>
                  </div>

                  <div className="insight-prediction-grid">
                    {insightResult.predictions.map((prediction, index) => {
                      const rawConfidence = prediction.confidence ?? "medium";

                      let confidenceLevel = "medium";

                      if (typeof rawConfidence === "number") {
                        if (rawConfidence >= 0.8) {
                          confidenceLevel = "high";
                        } else if (rawConfidence < 0.5) {
                          confidenceLevel = "low";
                        }
                      } else {
                        const normalizedConfidence =
                          String(rawConfidence).toLowerCase();

                        if (
                          normalizedConfidence === "high" ||
                          normalizedConfidence === "medium" ||
                          normalizedConfidence === "low"
                        ) {
                          confidenceLevel = normalizedConfidence;
                        }
                      }

                      const confidenceDisplay =
                        typeof rawConfidence === "number"
                          ? `${Math.round(rawConfidence * 100)}% confidence`
                          : `${confidenceLevel
                              .charAt(0)
                              .toUpperCase()}${confidenceLevel.slice(
                              1,
                            )} confidence`;

                      return (
                        <article
                          className={`insight-prediction-card ${confidenceLevel}`}
                          key={`${prediction.title}-${index}`}
                        >
                          <div className="insight-prediction-top">
                            <span className="insight-prediction-number">
                              {String(index + 1).padStart(2, "0")}
                            </span>

                            <span
                              className={`insight-prediction-confidence ${confidenceLevel}`}
                            >
                              {confidenceDisplay}
                            </span>
                          </div>

                          <div className="insight-prediction-icon">↗</div>

                          <span className="insight-prediction-label">
                            Forecast Signal
                          </span>

                          <h3>{prediction.title}</h3>

                          <p>{prediction.description}</p>

                          <div className="insight-prediction-note">
                            <span>Predictive insight</span>

                            <p>
                              This is an analytical forecast, not a guaranteed
                              outcome.
                            </p>
                          </div>
                        </article>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* =========================================
                    DAY 7 STEP 10 - BUSINESS STORY
                ========================================== */}

              {insightResult.businessStory && (
                <div className="insight-business-story-section">
                  <div className="insight-business-story-card">
                    <div className="insight-business-story-top">
                      <div>
                        <span className="insight-business-story-label">
                          Business Story
                        </span>

                        <h2>Executive Summary</h2>
                      </div>

                      <span className="insight-business-story-badge">
                        Decision Summary
                      </span>
                    </div>

                    <div className="insight-business-story-content">
                      <div className="insight-business-story-icon">ARIA</div>

                      <p>{insightResult.businessStory}</p>
                    </div>

                    <div className="insight-business-story-footer">
                      <span>Generated from the current analysis</span>

                      <strong>Insight Agent</strong>
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </section>
      )}
      {/* =====================================================
    DAY 8 - RL FEEDBACK AGENT
===================================================== */}

      {isInsightSuccess && insightResult && (
        <section className="feedback-agent-section">
          <div className="feedback-agent-header">
            <div>
              <span className="feedback-agent-label">Feedback Agent</span>

              <h2>Help ARIA Improve</h2>

              <p>
                Evaluate this analysis so ARIA can learn which insights and
                results are most useful.
              </p>
            </div>

            <span className="feedback-agent-badge">User Feedback</span>
          </div>
          {/* ===============================================
    OVERALL EXPERIENCE REACTION
=============================================== */}

          <div className="feedback-question-card">
            <span className="feedback-question-label">Overall Experience</span>

            <h3>How would you rate this analysis experience?</h3>

            <div className="feedback-reaction-group">
              {[
                {
                  value: 1,
                  emoji: "😞",
                  label: "Very Poor",
                },
                {
                  value: 2,
                  emoji: "🙁",
                  label: "Poor",
                },
                {
                  value: 3,
                  emoji: "😐",
                  label: "Neutral",
                },
                {
                  value: 4,
                  emoji: "🙂",
                  label: "Good",
                },
                {
                  value: 5,
                  emoji: "😄",
                  label: "Excellent",
                },
              ].map((reaction) => (
                <button
                  type="button"
                  key={reaction.value}
                  className={
                    reactionRating === reaction.value
                      ? "feedback-reaction active"
                      : "feedback-reaction"
                  }
                  onClick={() => setReactionRating(reaction.value)}
                >
                  <span className="feedback-reaction-emoji">
                    {reaction.emoji}
                  </span>

                  <span className="feedback-reaction-label">
                    {reaction.label}
                  </span>
                </button>
              ))}
            </div>
          </div>
          {/* ===============================================
          OVERALL USEFULNESS
      ================================================ */}

          <div className="feedback-question-card">
            <span className="feedback-question-label">Quality Feedback</span>

            <h3>Was this analysis useful?</h3>

            <div className="feedback-choice-group">
              <button
                type="button"
                className={
                  overallUseful === true
                    ? "feedback-choice-button active"
                    : "feedback-choice-button"
                }
                onClick={() => setOverallUseful(true)}
              >
                Useful
              </button>

              <button
                type="button"
                className={
                  overallUseful === false
                    ? "feedback-choice-button active"
                    : "feedback-choice-button"
                }
                onClick={() => setOverallUseful(false)}
              >
                Not Useful
              </button>
            </div>
          </div>

          {/* ===============================================
          STAR RATING
      ================================================ */}

          <div className="feedback-question-card">
            <span className="feedback-question-label">Overall Rating</span>

            <h3>Rate this analysis</h3>

            <div className="feedback-star-group">
              {[1, 2, 3, 4, 5].map((star) => (
                <button
                  type="button"
                  key={star}
                  className={
                    star <= overallRating
                      ? "feedback-star active"
                      : "feedback-star"
                  }
                  onClick={() => setOverallRating(star)}
                  aria-label={`Rate ${star} star${star === 1 ? "" : "s"}`}
                >
                  ★
                </button>
              ))}
            </div>

            {overallRating > 0 && (
              <p className="feedback-rating-text">{overallRating} out of 5</p>
            )}
          </div>
          {/* ===============================================
    BEST HYPOTHESIS SELECTION
=============================================== */}

          {insightResult.hypotheses?.length > 1 && (
            <div className="feedback-question-card">
              <span className="feedback-question-label">Best Result</span>

              <h3>Which hypothesis was most useful?</h3>

              <p>
                Select the explanation that was most valuable for understanding
                this analysis.
              </p>

              <div className="best-hypothesis-list">
                {insightResult.hypotheses.map((hypothesis, index) => (
                  <button
                    type="button"
                    key={`${hypothesis.title}-${index}`}
                    className={
                      bestHypothesis === index
                        ? "best-hypothesis-option active"
                        : "best-hypothesis-option"
                    }
                    onClick={() => setBestHypothesis(index)}
                  >
                    <span className="best-hypothesis-number">{index + 1}</span>

                    <div>
                      <strong>{hypothesis.title}</strong>

                      <small>Rank #{hypothesis.rank || index + 1}</small>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}
          {/* ===============================================
          CORRECTION / COMMENT
      ================================================ */}

          <div className="feedback-question-card">
            <span className="feedback-question-label">Correction</span>

            <h3>Add a correction or comment</h3>

            <p>
              Tell ARIA if something was interpreted incorrectly or if important
              business context is missing.
            </p>

            <textarea
              className="feedback-correction-input"
              value={feedbackCorrection}
              onChange={(event) => setFeedbackCorrection(event.target.value)}
              placeholder="Example: The April sales decline happened because the store was closed for one week."
              rows={4}
            />
          </div>

          {/* ===============================================
          SUBMIT
      ================================================ */}

          <div className="feedback-submit-area">
            <button
              type="button"
              className="feedback-submit-button"
              onClick={handleBasicFeedbackSubmit}
              disabled={
                feedbackStatus === "submitting" ||
                reactionRating === 0 ||
                overallUseful === null ||
                overallRating === 0 ||
                (requiresFeedbackComment && feedbackCorrection.trim() === "")
              }
            >
              {feedbackStatus === "submitting"
                ? "Submitting Feedback..."
                : "Submit Feedback"}
            </button>

            {(reactionRating === 0 ||
              overallUseful === null ||
              overallRating === 0) &&
              feedbackStatus !== "success" && (
                <span className="feedback-required-text">
                  Select an experience rating, usefulness, and a star rating
                  before submitting.
                </span>
              )}
          </div>

          {/* ===============================================
          SUCCESS
      ================================================ */}

          {feedbackStatus === "success" && submittedFeedback && (
            <div className="feedback-success-message">
              <strong>Feedback submitted successfully</strong>

              <p>Thank you for helping ARIA improve future analyses.</p>
            </div>
          )}

          {/* ===============================================
          ERROR
      ================================================ */}

          {feedbackStatus === "failed" && (
            <div className="feedback-error-message">
              <strong>Feedback could not be submitted</strong>

              <p>{feedbackError}</p>
            </div>
          )}
        </section>
      )}
    </div>
  );
}

export default Dashboard;
