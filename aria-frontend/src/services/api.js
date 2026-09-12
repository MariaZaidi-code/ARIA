// =========================================================
// ARIA API SERVICE
// =========================================================
//
// Connected to the ARIA FastAPI backend:
//
// React
//   ↓  fetch() through the Vite dev proxy (/api → :8000)
// FastAPI (/api/auth, /api/connect, /api/connect_file,
//          /api/extract_schema, /api/schema, /api/suggestions,
//          /api/ask, /api/insight)
//   ↓
// Real Schema / Goal / Insight Agents
//
// Every function returns the same shape the UI already expects
// ({ success, data }) so pages did not need to change.

import { getAuthToken } from "../utils/authStorage";

const API_BASE = "/api";

// =========================================================
// LLM MODE (chosen on the LLM Selection screen)
// =========================================================

const getLLMMode = () => {
  return localStorage.getItem("aria_llm_mode") || "local";
};

// =========================================================
// FETCH HELPER
// =========================================================
//
// Attaches the JWT, JSON-encodes the body, and converts FastAPI
// error payloads ({ "detail": "..." }) into thrown Errors.
// =========================================================

const request = async (path, options = {}) => {
  const headers = {
    ...(options.headers || {}),
  };

  const token = getAuthToken();

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const isJsonBody =
    options.body &&
    !(options.body instanceof FormData) &&
    !headers["Content-Type"];

  if (isJsonBody) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,

    headers,
  });

  let data;

  try {
    data = await response.json();
  } catch {
    data = {};
  }

  if (!response.ok) {
    const detail = data?.detail;

    const message =
      (typeof detail === "string" && detail) ||
      (Array.isArray(detail) && detail.map((item) => item?.msg).join("; ")) ||
      data?.message ||
      `Request failed (${response.status}).`;

    throw new Error(message);
  }

  return data;
};

// =========================================================
// VALUE HELPERS
// =========================================================

const toNumber = (value) => {
  if (typeof value === "number") {
    return value;
  }

  if (value === null || value === undefined || value === "") {
    return null;
  }

  const cleaned = String(value).replace(/,/g, "").trim();
  if (!/^-?[0-9]*\.?[0-9]+([eE][+-]?[0-9]+)?$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isNaN(parsed) ? null : parsed;
};

const formatValue = (value) => {
  if (value === null || value === undefined) {
    return "—";
  }

  const parsed = toNumber(value);

  if (parsed === null) {
    return String(value);
  }

  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(parsed);
};

const humanize = (key) => {
  return String(key || "")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const isIdLike = (key) => {
  const low = String(key || "").toLowerCase();

  return (
    low.endsWith("_id") ||
    low.endsWith("_key") ||
    low === "id" ||
    low === "key" ||
    low === "code"
  );
};

const isNumericColumn = (rows, key) => {
  let numeric = 0;

  let total = 0;

  for (const row of rows) {
    const value = row?.[key];

    if (value === null || value === undefined || value === "") {
      continue;
    }

    total += 1;

    if (toNumber(value) !== null) {
      numeric += 1;
    }
  }

  return total > 0 && numeric / total >= 0.7;
};

const isDateColumn = (rows, key) => {
  const low = String(key || "").toLowerCase();

  if (/(date|time|_at|day|month|year|period)/.test(low)) {
    const first = rows[0]?.[key];

    if (
      first !== null &&
      first !== undefined &&
      first !== "" &&
      !Number.isNaN(new Date(String(first)).getTime())
    ) {
      return true;
    }
  }

  let hits = 0;

  let total = 0;

  for (const row of rows.slice(0, 20)) {
    const value = row?.[key];

    if (value === null || value === undefined || value === "") {
      continue;
    }

    total += 1;

    const sv = String(value).trim();
    if (/^\d{1,4}(\.\d+)?$/.test(sv)) continue;
    if (!Number.isNaN(new Date(sv).getTime())) {
      hits += 1;
    }
  }

  return total > 0 && hits / total >= 0.7;
};

// =========================================================
// AUTHENTICATION
// =========================================================
//
// The login flow is handled by authStorage.authenticateLocalUser
// and authStorage.registerLocalUser, which POST to /api/auth/login
// and /api/auth/register respectively. The loginUser export is
// retained for backward compatibility but is not called anywhere
// in the current codebase.
//
// =========================================================

export const fetchSessionStatus = async () => {
  try {
    const data = await request("/session/status");
    return { success: true, data: data || {} };
  } catch {
    return { success: false, data: {} };
  }
};

export const disconnectSource = async () => {
  const data = await request("/disconnect", { method: "POST", body: JSON.stringify({}) });
  return { success: true, data };
};

export const connectDatabase = async (databaseDetails = {}) => {
  const payload = {
    provider: databaseDetails?.provider || getLLMMode(),

    source_type: "relational",

    db_type: databaseDetails?.dbType || databaseDetails?.sourceType || "postgresql",

    host: databaseDetails?.host || "localhost",

    port: Number(databaseDetails?.port || 5432),

    db: databaseDetails?.db || null,

    user: databaseDetails?.user || null,

    password: databaseDetails?.password || null,

    db_schema: databaseDetails?.dbSchema || "public",
  };

  try {
    const data = await request("/connect", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    return { success: true, message: "Database connected.", data };
  } catch (error) {
    return {
      success: false,
      message: error?.message || (typeof error === "string" ? error : "Connection failed."),
    };
  }
};

// =========================================================
// FILE CONNECTION (CSV)
// =========================================================

export const connectFile = async (file, provider = "local") => {
  if (!file) {
    return {
      success: false,

      message: "No file selected.",
    };
  }

  const formData = new FormData();

  formData.append("provider", provider || getLLMMode());

  formData.append("file", file);

  const data = await request("/connect_file", {
    method: "POST",

    body: formData,
  });

  return {
    success: true,

    message: "File uploaded and profiled.",

    data,
  };
};

// =========================================================
// PDF DOCUMENT CONNECTION
// =========================================================

export const connectPdf = async (file, provider = "local") => {
  if (!file) {
    return { success: false, message: "No file selected." };
  }
  const formData = new FormData();
  formData.append("provider", provider || getLLMMode());
  formData.append("file", file);
  try {
    const data = await request("/connect_pdf", { method: "POST", body: formData });
    return { success: true, message: "PDF uploaded and processing started.", data };
  } catch (error) {
    return { success: false, message: error?.message || "PDF upload failed." };
  }
};

// =========================================================
// DOCUMENT MANAGEMENT
// =========================================================

export const listDocuments = async () => {
  const data = await request("/documents");
  return { success: true, data: data?.documents || data?.data || [] };
};

export const getDocument = async (documentId) => {
  const data = await request(`/documents/${documentId}`);
  return { success: true, data: data?.document };
};

export const searchDocuments = async (query, documentIds = null, k = 10) => {
  const data = await request("/documents/search", {
    method: "POST",
    body: JSON.stringify({ query, document_ids: documentIds, k }),
  });
  return { success: true, data: data?.results || [] };
};

export const searchDocument = async (documentId, query, k = 10) => {
  const data = await request(`/documents/${documentId}/search`, {
    method: "POST",
    body: JSON.stringify({ query, k }),
  });
  return { success: true, data: data?.results || [] };
};

export const deleteDocument = async (documentId) => {
  const data = await request(`/documents/${documentId}`, {
    method: "DELETE",
  });
  return { success: true, data };
};

export const retryDocument = async (documentId) => {
  const data = await request(`/documents/${documentId}/retry`, {
    method: "POST",
  });
  return { success: true, data: data?.document };
};

// =========================================================
// SCHEMA AGENT
// =========================================================

export const fetchSchema = async () => {
  // Run an extraction if needed; ignore failures for sources whose
  // schema mapping was already written by the connect step.
  try {
    await request("/extract_schema", {
      method: "POST",

      body: JSON.stringify({}),
    });
  } catch (error) {
    console.warn("Schema extraction skipped:", error?.message);
  }

  const data = await request("/schema");

  return {
    success: true,

    data: data?.schema || data || {},
  };
};

// =========================================================
// QUESTION SUGGESTIONS
// =========================================================

export const getQuestionSuggestions = async (question, sourceContext = {}) => {
  void question;

  void sourceContext;

  try {
    const data = await request("/suggestions", {
      method: "POST",

      body: JSON.stringify({ limit: 8 }),
    });

    return {
      success: true,

      data: data?.suggestions || [],
    };
  } catch (error) {
    console.error("Suggestion error:", error);

    return {
      success: false,

      data: [],

      message: error?.message,
    };
  }
};

// =========================================================
// GOAL TYPE LABEL (derived for the UI badge)
// =========================================================

const deriveGoalType = (data) => {
  const kpis = data?.kpi_alignment || (data?.analysis_plan?.measures?.length ? data.analysis_plan : null);

  if (kpis && Object.keys(kpis).length > 0) {
    return "KPI Analysis";
  }

  const questionText = String(data?.user_goal || data?.question || "").toLowerCase();

  if (/(trend|over time|monthly|weekly|daily|quarter)/.test(questionText)) {
    return "Trend Analysis";
  }

  if (/(compare|comparison|versus|\bvs\b|difference)/.test(questionText)) {
    return "Comparative Analysis";
  }

  if (data?.goal?.analysis_type === "predictive" || /forecast|predict/.test(questionText)) {
    return "Predictive Analysis";
  }

  if (/top\s+\d+/.test(questionText)) {
    return "Ranking Analysis";
  }

  return "Business Question";
};

// =========================================================
// GOAL AGENT
// =========================================================

export const analyzeQuestion = async (question, llmMode, sourceContext = {}, multiTurnContext = null, options = {}) => {
  void llmMode;

  void sourceContext;

  const body = { goal: String(question || "") };
  if (multiTurnContext?.previousGoal) {
    body.previous_goal = multiTurnContext.previousGoal;
  }
  if (multiTurnContext?.previousResult) {
    body.previous_result = multiTurnContext.previousResult;
  }
  if (multiTurnContext?.conversationId) {
    body.conversation_id = multiTurnContext.conversationId;
  }

  const data = await request("/ask", {
    method: "POST",
    body: JSON.stringify(body),
    ...(options.signal ? { signal: options.signal } : {}),
  });

  const status = data?.status || "success";

  const failed =
    status !== "success" && status !== "clarification";

  if (failed) {
    throw new Error(
      data?.message || "The Goal Agent could not answer this goal.",
    );
  }

  const preprocessing = Array.isArray(data?.preprocessing)
    ? data.preprocessing
    : Array.isArray(data?.preprocessing?.notes)
      ? data.preprocessing.notes
      : [];

  const goalData = {
    interpretedGoal:
      data?.question ||
      data?.user_goal ||
      (status === "clarification" ? data?.message : null) ||
      String(question || ""),

    goalType: deriveGoalType(data),

    clarificationRequired: status === "clarification",

    clarificationMessage: status === "clarification" ? data?.message || "" : "",

    relevantTables: data?.data_selection?.tables || data?.kpi_alignment?.tables || [],

    joinPlan: Array.isArray(data?.join_path) ? data.join_path : [],

    generatedSql: data?.sql_used || data?.sql || "",

    preprocessing,

    processedDataSummary: {
      rowCount: data?.row_count ?? 0,

      columns: data?.columns || [],
    },

    nextAgent: "Insight Agent",

    // Raw processed rows: consumed by generateAnalyticsResult to build
    // KPIs / charts / table from the real data.
    data: data?.data || [],

    message: data?.message || "",

    warnings: data?.warnings || [],

    proactiveInsights: data?.proactive_insights || [],
    anomalies: data?.anomalies || [],
    dataQualityWarnings: data?.data_quality_warnings || [],
    explanation: data?.explanation || null,
    confidence: data?.confidence || "high",

    historyId: data?.history_id || null,
    suggestedQuestions: data?.suggested_questions || [],
    provenance: data?.provenance || null,
    conversationId: data?.conversation_id || null,
    turnNumber: data?.turn_number || null,
    // Explainability envelope (§20-21): why, story, chart spec, consistency.
    why: data?.why || null,
    story: data?.story || "",
    chartSpec: data?.chart_spec || null,
    consistency: data?.consistency || null,
    // Server-defined display metadata (t.txt-5): render as-is, never recompute.
    display: data?.display || null,
  };

  return {
    success: true,

    data: goalData,
  };
};

// =========================================================
// DAY 6 - ANALYTICS RESULT BUILDER
// =========================================================
//
// Builds KPIs, charts, and the result table from the processed
// rows the Goal Agent actually returned.
// =========================================================

export const generateAnalyticsResult = async (goalResult = {}) => {
  const rows = Array.isArray(goalResult?.data) ? goalResult.data : [];

  const empty = {
    kpis: [],

    charts: [],

    table: {
      columns: [],

      rows: [],
    },
  };

  if (!rows.length) {
    return {
      success: true,

      data: empty,
    };
  }

  const keys = Object.keys(rows[0]);

  const allNumeric = keys.filter((key) => isNumericColumn(rows, key));

  const allDates = keys.filter((key) => isDateColumn(rows, key));

  const categorical = keys.filter(
    (key) => !allNumeric.includes(key) && !allDates.includes(key),
  );

  const measures = allNumeric.filter((key) => !isIdLike(key));

  const usableMeasures = measures.length ? measures : allNumeric;

  const dimension = categorical.find((key) => !isIdLike(key)) || categorical[0];

  const timeColumn = allDates.find((key) => !isIdLike(key)) || allDates[0];

  const measure = usableMeasures[0];

  // ---------- KPIs ----------

  const kpis = usableMeasures.slice(0, 4).map((column) => {
    const values = rows
      .map((row) => toNumber(row[column]))
      .filter((value) => value !== null);

    const sum = values.reduce((total, value) => total + value, 0);

    const mean = values.length ? sum / values.length : 0;

    return {
      label: values.length ? `${humanize(column)} (Avg)` : humanize(column),

      value: values.length ? formatValue(mean) : "—",
    };
  });

  // ---------- Charts ----------

  const charts = [];

  if (dimension && measure && rows.length >= 2) {
    const chartData = rows.slice(0, 12).map((row) => ({
      [dimension]: row[dimension] ?? String(row[dimension] ?? ""),

      [measure]: toNumber(row[measure]) ?? 0,
    }));

    charts.push({
      title: `${humanize(measure)} by ${humanize(dimension)}`,

      type: "bar",

      xKey: dimension,

      yKey: measure,

      xLabel: humanize(dimension),

      yLabel: humanize(measure),

      data: chartData,
    });
  } else if (measure) {
    const chartData = rows.slice(0, 10).map((row, index) => ({
      _rank: `${humanize(measure)} #${index + 1}`,

      [measure]: toNumber(row[measure]) ?? 0,
    }));

    charts.push({
      title: `${humanize(measure)} (top values)`,

      type: "horizontal-bar",

      xKey: "_rank",

      yKey: measure,

      xLabel: humanize(measure),

      yLabel: "Value",

      data: chartData,
    });
  }

  if (dimension && measure && rows.length) {
    const grouped = {};

    for (const row of rows) {
      const groupKey = String(row[dimension] ?? "—");

      grouped[groupKey] = (grouped[groupKey] || 0) + (toNumber(row[measure]) || 0);
    }

    const entries = Object.entries(grouped)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8);

    if (entries.length >= 2) {
      charts.push({
        title: `${humanize(measure)} share by ${humanize(dimension)}`,

        type: "donut",

        nameKey: dimension,

        valueKey: measure,

        data: entries.map(([name, value]) => ({
          [dimension]: name,

          [measure]: value,
        })),
      });
    }
  }

  if (timeColumn && measure) {
    const chartData = [...rows]
      .sort(
        (a, b) => new Date(String(a[timeColumn])) - new Date(String(b[timeColumn])),
      )
      .slice(0, 30)
      .map((row) => ({
        [timeColumn]: String(row[timeColumn]),

        [measure]: toNumber(row[measure]) ?? 0,
      }));

    charts.push({
      title: `${humanize(measure)} over time`,

      type: "line",

      xKey: timeColumn,

      yKey: measure,

      xLabel: humanize(timeColumn),

      yLabel: humanize(measure),

      data: chartData,
    });
  } else if (allNumeric.length >= 2 && !dimension) {
    const xColumn = allNumeric[0];

    const yColumn = allNumeric[1];

    const chartData = rows.slice(0, 30).map((row) => ({
      [xColumn]: toNumber(row[xColumn]) ?? 0,

      [yColumn]: toNumber(row[yColumn]) ?? 0,
    }));

    charts.push({
      title: `${humanize(xColumn)} vs ${humanize(yColumn)}`,

      type: "scatter",

      xKey: xColumn,

      yKey: yColumn,

      xLabel: humanize(xColumn),

      yLabel: humanize(yColumn),

      data: chartData,
    });
  }

  // ---------- Table ----------

  const table = {
    columns: keys.map((key) => ({
      key,

      label: humanize(key),
    })),

    rows: rows.slice(0, 50),
  };

  return {
    success: true,

    data: {
      kpis,

      charts: charts.slice(0, 3),

      table,
    },
  };
};

// =========================================================
// INSIGHT AGENT
// =========================================================

const confidenceToNumber = (value) => {
  if (typeof value === "number") {
    return value;
  }

  const normalized = String(value || "").toLowerCase();

  if (normalized === "high") {
    return 0.9;
  }

  if (normalized === "medium") {
    return 0.6;
  }

  if (normalized === "low") {
    return 0.35;
  }

  return 0.5;
};

const adaptHypotheses = (hypotheses) => {
  return (hypotheses || []).slice(0, 4).map((item, index) => ({
    title: item?.hypothesis || `Possible explanation ${index + 1}`,

    description: item?.basis || "",

    rank: index + 1,

    confidence: confidenceToNumber(item?.confidence),

    evidence: item?.basis ? [item.basis] : [],
  }));
};

const adaptTrends = (trends) => {
  return (trends || []).slice(0, 3).map((item) => {
    const increasing = item?.direction === "increasing";

    const decreasing = item?.direction === "decreasing";

    const change =
      item?.pct_change !== null && item?.pct_change !== undefined
        ? ` (${item.pct_change > 0 ? "+" : ""}${item.pct_change}% change)`
        : "";

    return {
      title: `${humanize(item?.dimension)} movement`,

      description: `${humanize(item?.columns?.[0] || item?.dimension)} is ${
        increasing ? "trending upward" : decreasing ? "trending downward" : "moving in a mixed pattern"
      }${change}.`,

      direction: increasing ? "up" : decreasing ? "down" : "mixed",
    };
  });
};

const adaptAnomalies = (anomalies) => {
  return (anomalies || []).slice(0, 5).map((item) => {
    const zScore = Number(item?.z_score || 0);

    return {
      title: `${humanize(item?.column)} outlier`,

      description: `${humanize(item?.column)} = ${formatValue(item?.value)} at row ${
        Number(item?.row || 0) + 1
      } is ${item?.note || "outside the normal band"} (z-score ${zScore}).`,

      severity: zScore >= 3 ? "high" : zScore >= 2.5 ? "medium" : "low",
    };
  });
};

const adaptPredictions = (predictions) => {
  if (!predictions) {
    return [];
  }

  if (Array.isArray(predictions)) {
    return predictions.slice(0, 4).map((item, index) => ({
      title: item?.title || `Forecast ${index + 1}`,

      description: item?.description || item?.reason || "",

      confidence: confidenceToNumber(item?.confidence),
    }));
  }

  if (predictions.valid && Array.isArray(predictions.points) && predictions.points.length) {
    const field = predictions.column || "metric";

    return predictions.points.slice(0, 4).map((point) => {
      const label = point?.date ?? point?.period ?? "Next period";

      const forecast = point?.forecast ?? point?.value ?? point?.fitted;

      const confidence =
        predictions.accuracy_pct !== null && predictions.accuracy_pct !== undefined
          ? Number(predictions.accuracy_pct) / 100
          : predictions.reliability === "high" || predictions.reliability === "medium"
            ? confidenceToNumber(predictions.reliability)
            : "medium";

      return {
        title: `${humanize(field)} · ${label}`,

        description:
          forecast !== null && forecast !== undefined
            ? `Projected value ${formatValue(forecast)}${
                point?.actual !== null && point?.actual !== undefined
                  ? ` (last actual ${formatValue(point.actual)})`
                  : ""
              }.`
            : point?.reason || "Forecast point.",

        confidence,
      };
    });
  }

  if (predictions.reason) {
    return [
      {
        title: "Forecast not generated",

        description: predictions.reason,

        confidence: "medium",
      },
    ];
  }

  return [];
};

export const generateInsights = async (goalResult, analyticsResult) => {
  void goalResult;

  void analyticsResult;

  const data = await request("/insight", {
    method: "POST",

    body: JSON.stringify({}),
  });

  const insights = data?.insights || {};

  const keyInsights = [];

  for (const kpi of (insights.kpis || []).slice(0, 3)) {
    const hasValue = kpi?.sum !== null && kpi?.sum !== undefined;

    keyInsights.push({
      title: `Total ${humanize(kpi?.column)}`,

      description: hasValue
        ? `Sum of ${humanize(kpi.column)} is ${formatValue(kpi.sum)}${
            kpi.mean !== null && kpi.mean !== undefined
              ? ` with an average of ${formatValue(kpi.mean)}`
              : ""
          }${kpi.count ? ` across ${kpi.count} rows` : ""}.`
        : `${humanize(kpi?.column)} has ${kpi?.count || 0} values${
            kpi?.max !== null && kpi?.max !== undefined
              ? `, peaking at ${formatValue(kpi.max)}`
              : ""
          }.`,

      impact: "high",
    });
  }

  const firstTrend = (insights.trends || [])[0];

  if (firstTrend) {
    keyInsights.push({
      title: `${humanize(firstTrend?.dimension || "data")} trend`,

      description: adaptTrends([firstTrend])[0]?.description || "",

      impact: "medium",
    });
  }

  const recommendations = (
    insights.prescriptions?.actions || []
  ).slice(0, 5).map((action, index) => ({
    title: action,

    description: action,

    priority: ["high", "medium", "low"][index % 3],
  }));

  return {
    success: true,

    data: {
      keyInsights: keyInsights.slice(0, 3),

      trends: adaptTrends(insights.trends),

      anomalies: adaptAnomalies(insights.anomalies),

      hypotheses: adaptHypotheses(insights.hypotheses),

      recommendations,

      predictions: adaptPredictions(insights.predictions),

      businessStory: insights.business_story || "",
    },
  };
};

// =========================================================
// DAY 8 - FEEDBACK AGENT
// =========================================================
//
// The backend has no feedback endpoint yet; feedback is recorded
// in the local history session so it is not lost.
// =========================================================

export const submitFeedback = async (feedbackData = {}) => {
  try {
    const data = await request("/feedback", {
      method: "POST",
      body: JSON.stringify({
        message: feedbackData?.message || feedbackData?.text || "",
        category: feedbackData?.category || "general",
      }),
    });
    return { success: true, message: data?.message || "Thanks for your feedback.", data };
  } catch (error) {
    console.warn("Feedback submit failed (non-blocking):", error?.message);
    return { success: true, message: "Thanks for your feedback." };
  }
};
