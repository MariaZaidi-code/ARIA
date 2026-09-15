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

// Centralized API base (respects VITE_API_BASE, defaults to /api so the
// Vite dev proxy /api -> :8000 keeps working). Import API_BASE from here
// everywhere instead of hardcoding "/api".
export const API_BASE = (import.meta?.env?.VITE_API_BASE || "/api").replace(/\/$/, "");

// Versioned storage (aria.v1.*) with legacy-key fallback. Static import is
// cycle-safe: storage.js is dependency-free.
import { storage as versionedStorage } from "../utils/storage.js";

const storageHelperGet = (key, fallback) => {
  try {
    return versionedStorage.getString(key, fallback) ?? fallback;
  } catch {
    return fallback;
  }
};

// Consistent 401 handling: clear the (cookie-based) session markers and
// notify the app to return to login. Pages listen for "aria:unauthorized".
export const handleUnauthorized = () => {
  try {
    localStorage.removeItem("aria_auth_token"); // legacy JWT, cookie auth now
    localStorage.removeItem("aria_auth_user");
  } catch { /* ignore */ }
  try {
    window.dispatchEvent(new Event("aria:unauthorized"));
  } catch { /* ignore */ }
};

// request ids: generated per request, sent as X-Request-ID and echoed
// back on errors. Prefer the backend's value when present.
const newRequestId = () => {
  try {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  } catch { /* fall through */ }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
};

// Normalize a caller path to a single `/api/*` URL. API_BASE already ends
// with `/api` (or a custom VITE_API_BASE), so a caller passing the full
// `/api/copilot` prefix would double it to `/api/api/copilot` — strip the
// duplicate. Bare `copilot` gains its leading slash.
const resolvePath = (path) => {
  let p = String(path || "");
  if (!p.startsWith("/")) p = `/${p}`;
  const base = API_BASE.replace(/\/$/, "");
  if (p === "/api" || p.startsWith("/api/")) {
    const suffix = p.slice("/api".length) || "/";
    if (base === "/api" || base.endsWith("/api")) return `${base}${suffix}`;
  }
  return `${base}${p}`;
};

// Unified client timeout: 60s floor / 120s ceiling (heavy LLM + forecast
// calls need headroom; chatty reads stay snappy). Single knob for the
// whole frontend — services/api.js and figma/lib/decisionCenterApi.ts
// share it via apiFetch (VITE_API_TIMEOUT_MS overrides, then clamped).
const RAW_TIMEOUT_MS = Number(import.meta?.env?.VITE_API_TIMEOUT_MS || 90000);
const REQUEST_TIMEOUT_MS = Math.max(60000, Math.min(120000, RAW_TIMEOUT_MS));
export const API_TIMEOUT_MS = REQUEST_TIMEOUT_MS;

// =========================================================
// LLM MODE (chosen on the LLM Selection screen)
// =========================================================

const getLLMMode = () => {
  try {
    const v = storageHelperGet("aria.v1.ui.llm_mode", null);
    if (v) return v;
  } catch { /* fall through to legacy key */ }
  try {
    return localStorage.getItem("aria_llm_mode") || "local";
  } catch {
    return "local";
  }
};

// =========================================================
// FETCH HELPER
// =========================================================
//
// Attaches the JWT, JSON-encodes the body, and converts FastAPI
// error payloads ({ "detail": "..." }) into thrown Errors.
// =========================================================

// Cookie auth: the backend sets an httpOnly `aria_token` cookie on
// login/register. No Authorization header is sent (omitted entirely —
// never `Bearer null`/empty); every request uses credentials:include so
// the cookie travels automatically. On 401 the session is cleared and the
// app is asked to return to login.
const request = async (path, options = {}) => {
  const { signal: externalSignal, ...rest } = options || {};
  const headers = {
    ...(rest.headers || {}),
  };
  // Strip any legacy Authorization header callers may still pass.
  delete headers["Authorization"];
  delete headers["authorization"];

  const isJsonBody =
    rest.body &&
    !(rest.body instanceof FormData) &&
    !headers["Content-Type"];

  if (isJsonBody) {
    headers["Content-Type"] = "application/json";
  }

  // X-Request-ID: trace every request; backend echoes it on errors.
  const requestId = headers["X-Request-ID"] || headers["x-request-id"] || newRequestId();
  headers["X-Request-ID"] = requestId;

  const controller = new AbortController();
  const onExternalAbort = () => {
    try {
      controller.abort(externalSignal?.reason);
    } catch {
      try { controller.abort(); } catch { /* ignore */ }
    }
  };
  if (externalSignal) {
    if (externalSignal.aborted) {
      const aborted = new Error("The operation was aborted.");
      aborted.name = "AbortError";
      throw aborted;
    }
    try {
      externalSignal.addEventListener("abort", onExternalAbort, { once: true });
    } catch { /* ignore */ }
  }
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(resolvePath(path), {
      ...rest,

      headers,
      credentials: "include",
      signal: controller.signal,
    });
  } catch (err) {
    clearTimeout(timeout);
    try {
      externalSignal?.removeEventListener?.("abort", onExternalAbort);
    } catch { /* ignore */ }
    // A caller-cancelled request (refresh/double-click race) must stay an
    // AbortError so UI race guards can ignore it — never a timeout.
    if (err?.name === "AbortError" && externalSignal?.aborted) throw err;
    if (err?.name === "AbortError") {
      const error = new Error(`Request timed out after ${REQUEST_TIMEOUT_MS / 1000}s.`);
      error.status = 0;
      error.code = "TIMEOUT";
      error.requestId = requestId;
      throw error;
    }
    const error = new Error("Network error: backend unreachable.");
    error.status = 0;
    error.code = "NETWORK_ERROR";
    error.requestId = requestId;
    throw error;
  }
  clearTimeout(timeout);
  try {
    externalSignal?.removeEventListener?.("abort", onExternalAbort);
  } catch { /* ignore */ }

  let data;
  let jsonOk = true;

  try {
    data = await response.json();
  } catch {
    jsonOk = false;
    data = {};
  }

  if (!response.ok) {
    // Never turn failures into empty dashboards: surface a real Error.
    // 401 clears the cookie session and routes back to login.
    if (response.status === 401) {
      handleUnauthorized();
    }
    const norm = normalizeApiError(data, response.status, response.headers);

    const error = new Error(norm.message);
    error.status = response.status;
    error.code = norm.code;
    error.requestId = norm.requestId || requestId;
    throw error;
  }

  return data;
};

// Public centralized client for pages that still need raw fetch semantics.
// Wraps request() so every call uses API_BASE + credentials:include, full
// res.ok handling (2xx/401/403/404/422/429/5xx/invalid JSON), and 401
// session cleanup. Prefer this over raw fetch("/api/...").
export const apiFetch = (path, options = {}) => request(path, options);

// =========================================================
// CENTRALIZED ERROR NORMALIZATION (single shared client layer)
// =========================================================
//
// Backend response -> standard frontend error object:
//   { message, code, requestId, status } -> UI.
// Pages/components must source the object centrally via normalizeApiError()
// or the thrown Error's .code/.requestId/.status fields, and may keep their
// own copy while rendering a concise message + Request ID (never stacks).
export const normalizeApiError = (data, status = 0, headers = null) => {
  const body = data && typeof data === "object" ? data : {};
  let raw = "";
  const detail = body?.detail;
  if (typeof detail === "string" && detail) raw = detail;
  else if (Array.isArray(detail))
    raw = detail.map((item) => item?.msg || item?.detail || JSON.stringify(item)).join("; ");
  else raw = body?.message || body?.error?.message || "";
  // Sanitize: never surface SQL / traces / raw JSON to the UI.
  let message = String(raw || "").trim();
  if (!message || /select\s.+\sfrom|traceback|exception|stack trace/i.test(message)) {
    message = status === 401 ? "Session expired. Please sign in again."
      : status === 403 ? "Read-only on this device."
      : status === 404 ? "Not found."
      : status === 429 ? "Too many requests. Try again shortly."
      : status >= 500 ? "Server error. Try again."
      : `Request failed (${status || "network"}).`;
  }
  message = message.slice(0, 200);
  let headerId = "";
  try {
    headerId = (typeof headers?.get === "function" ? headers.get("X-Request-ID") : headers?.["X-Request-ID"]) || "";
  } catch { headerId = ""; }
  const requestId = body?.request_id || body?.requestId || body?.error?.request_id || headerId || "";
  const code = body?.code || body?.error?.code
    || (status === 401 ? "UNAUTHORIZED" : status === 403 ? "FORBIDDEN"
      : status === 404 ? "NOT_FOUND" : status === 429 ? "RATE_LIMITED"
      : status >= 500 ? "SERVER_ERROR" : status === 0 ? "NETWORK_ERROR" : "REQUEST_FAILED");
  return { message, code, requestId, status };
};

// =========================================================
// VALUE HELPERS
// =========================================================
//
// P3 §27/§47 contract: every backend payload (connect, schema, ask,
// insights, forecast, prediction, prescription, hypothesis,
// decision-center, copilot, RAG) is consumed defensively — null, missing,
// empty arrays, errors, and partial results all render as "—" or a useful
// empty state, never undefined/null/NaN/blank/raw exceptions.

export const safeList = (v) => (Array.isArray(v) ? v : []);

export const safeText = (v, fallback = "—") => {
  if (v === null || v === undefined) return fallback;
  const s = String(v).trim();
  return s === "" || s.toLowerCase() === "undefined" || s.toLowerCase() === "null" || s.toLowerCase() === "nan"
    ? fallback
    : String(v);
};

export const safeNumberText = (v, fallback = "—") => {
  const n = toNumber(v);
  return n === null || Number.isNaN(n) ? fallback : formatValue(n);
};

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
  // LLM mode (local/cloud/...) and DB provider (postgresql/mysql/...) are
  // independent. Backend ConnectRequest.provider = LLM mode, db_type = DB
  // engine. Never derive one from the other.
  const LLM_MODES = ["local", "cloud", "deepseek", "omniroute", "grok"];
  const DB_TYPES = ["postgresql", "mysql"];
  const pickLlmMode = () => {
    if (LLM_MODES.includes(databaseDetails?.llmMode)) return databaseDetails.llmMode;
    if (LLM_MODES.includes(databaseDetails?.provider)) return databaseDetails.provider;
    return getLLMMode();
  };
  const pickDbType = () => {
    if (DB_TYPES.includes(databaseDetails?.dbType)) return databaseDetails.dbType;
    if (DB_TYPES.includes(databaseDetails?.dbProvider)) return databaseDetails.dbProvider;
    // sourceType may carry the DB engine ("postgresql"/"mysql") from the
    // Data page; file kinds ("csv"/"pdf") must NOT leak into db_type.
    if (DB_TYPES.includes(databaseDetails?.sourceType)) return databaseDetails.sourceType;
    if (DB_TYPES.includes(databaseDetails?.provider) && !LLM_MODES.includes(databaseDetails?.provider)) {
      return databaseDetails.provider;
    }
    return "postgresql";
  };
  const payload = {
    provider: pickLlmMode(),

    source_type: "relational",

    db_type: pickDbType(),

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
  // P3 §32 performance: reuse cached metadata; only run extraction when the
  // cached schema is missing/empty so we never re-extract, re-embed, or
  // reload unchanged datasets on every call.
  try {
    const cached = await request("/schema");
    const tables = cached?.schema?.tables || cached?.tables || {};
    if (cached?.schema && Object.keys(tables).length > 0) {
      return { success: true, data: cached?.schema || cached || {}, cached: true };
    }
  } catch {
    // Fall through to extraction when no usable cache exists.
  }
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
  // Context-aware analytics context (metric/time_range/filters/grouping/
  // dataset/previous_context). Carried from the shared cross-module context
  // so "this period / previous period" resolves dynamically server-side.
  const ctx = sourceContext || {};
  for (const k of ["metric", "time_range", "filters", "grouping", "dataset", "previous_context"]) {
    if (ctx[k] !== undefined && ctx[k] !== null && ctx[k] !== "") body[k] = ctx[k];
  }
  // Shared-context fallback (never overrides explicit call-site context).
  // Reads the session handoff key first, then the established localStorage
  // cross-module key (aria_analysis_context: metric/dataset/date/filters/
  // dimension), so "this period / previous period" resolves dynamically.
  try {
    let shared = {};
    try { shared = JSON.parse(sessionStorage.getItem("aria_shared_context") || "{}") || {}; } catch { shared = {}; }
    if (!shared || typeof shared !== "object" || Object.keys(shared).length === 0) {
      try { shared = JSON.parse(localStorage.getItem("aria_analysis_context") || "{}") || {}; } catch { shared = {}; }
    }
    if (shared && typeof shared === "object") {
      if (!body.metric && shared.metric) body.metric = shared.metric;
      if (!body.grouping && (shared.dimensions || shared.dimension)) {
        body.grouping = shared.dimensions || shared.dimension;
      }
      if (!body.time_range && (shared.period || shared.date || shared.granularity)) {
        body.time_range = {
          ...(typeof shared.period === "string" ? { label: shared.period } : {}),
          ...(shared.date ? { start: shared.date } : {}),
          ...(shared.granularity ? { granularity: shared.granularity } : {}),
        };
      }
      if (!body.filters && shared.filters) body.filters = shared.filters;
      if (!body.dataset && shared.dataset) body.dataset = shared.dataset;
    }
  } catch { /* best-effort */ }

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
    // Stable analytics contract (AI-Analytics 1-8, 17-20): rendered as-is,
    // never fabricated client-side. Missing keys render as empty states.
    interpretedIntent: data?.interpreted_intent || null,
    answer: data?.answer || data?.message || "",
    findings: Array.isArray(data?.findings) ? data.findings : [],
    evidence: Array.isArray(data?.evidence) ? data.evidence : [],
    visualization: data?.visualization || null,
    limitations: Array.isArray(data?.limitations) ? data.limitations : [],
    possibleDrivers: Array.isArray(data?.possible_drivers) ? data.possible_drivers : [],
    hypothesis: data?.hypothesis || null,
    recommendations: Array.isArray(data?.recommendations) ? data.recommendations : [],
    followUpQuestions: Array.isArray(data?.follow_up_questions)
      ? data.follow_up_questions
      : (data?.suggested_questions || []),
    comparisonPeriod: data?.comparison_period || null,
    resultStatus: data?.result_status || data?.status || "success",
    resultMessage: data?.result_message || "",
    metric: data?.metric ?? null,
    dimensions: Array.isArray(data?.dimensions) ? data.dimensions : [],
    filters: data?.filters ?? null,
    timeRange: data?.time_range ?? null,
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

// NOTE: the legacy POST /api/insight client (generateInsights) was removed.
// Insights re-analyze via GET /api/insights from the Insights page.

// =========================================================
// DAY 8 - FEEDBACK AGENT
// =========================================================
//
// The backend has no feedback endpoint yet; feedback is recorded
// in the local history session so it is not lost.
// =========================================================

// =========================================================
// INTELLIGENCE MODULE (Explore / Hypotheses / Goals / What-If / Reports)
// =========================================================
//
// Frontend renders backend truth only: every helper below forwards to
// GET/POST /api/intelligence/* via apiFetch (credentials:include,
// 60-120s clamped timeout, centralized 401 handling). List endpoints
// accept server-side search/filter/sort/pagination params — never load
// everything and filter client-side. No confidence/priority/impact math
// lives in React; the backend computes, the UI formats and displays.

const intelQuery = (params = {}) => {
  const parts = [];
  for (const [k, v] of Object.entries(params || {})) {
    if (v === undefined || v === null || v === "") continue;
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item !== undefined && item !== null && item !== "") {
          parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(item))}`);
        }
      }
    } else {
      parts.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    }
  }
  return parts.length ? `?${parts.join("&")}` : "";
};

export const intelligenceApi = {
  // ---- Explore ----
  // GET /api/intelligence/meta -> { metrics, breakdowns, time_grains,
  //   comparisons, date_ranges, ... } — populates every dropdown.
  getMeta: async () => {
    const data = await request("/intelligence/meta");
    return { success: true, data: data?.data || data || {} };
  },

  // POST /api/intelligence/explore { metric, breakdown, secondary_breakdown,
  //   time_grain, comparison, date_range, filters } -> { trend, observation,
  //   breakdown_rows, ... } — all numbers computed server-side.
  runExplore: async (payload = {}) => {
    const data = await request("/intelligence/explore", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  // ---- Hypotheses ----
  // GET /api/intelligence/hypotheses with server-side search/filter/sort/
  // pagination. Never show "schema-discovered lever" or FK-as-driver rows:
  // the backend must not send them; the UI additionally drops them.
  listHypotheses: async (params = {}) => {
    const data = await request(`/intelligence/hypotheses${intelQuery(params)}`);
    return {
      success: true,
      data: data?.data || data?.items || [],
      total: data?.total ?? data?.count ?? null,
      page: data?.page ?? params.page ?? null,
      pageSize: data?.page_size ?? params.page_size ?? null,
    };
  },

  getHypothesis: async (id) => {
    const data = await request(`/intelligence/hypotheses/${encodeURIComponent(id)}`);
    return { success: true, data: data?.data || data || {} };
  },

  // ---- Goals (CRUD, status persists server-side) ----
  listGoals: async (params = {}) => {
    const data = await request(`/intelligence/goals${intelQuery(params)}`);
    return {
      success: true,
      data: data?.data || data?.items || [],
      total: data?.total ?? data?.count ?? null,
    };
  },

  createGoal: async (payload = {}) => {
    const data = await request("/intelligence/goals", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  updateGoal: async (id, payload = {}) => {
    const data = await request(`/intelligence/goals/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  deleteGoal: async (id) => {
    const data = await request(`/intelligence/goals/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return { success: true, data: data?.data || data || {} };
  },

  // ---- What-If (slider range + results both from backend) ----
  // GET /api/intelligence/what-if/meta -> { variables, change_types,
  //   ranges: { [variable]: { min, max, step, ... } }, apply_targets }
  getWhatIfMeta: async () => {
    const data = await request("/intelligence/what-if/meta");
    return { success: true, data: data?.data || data || {} };
  },

  // POST /api/intelligence/what-if/run { variable, change_type,
  //   change_value, apply_to } -> { projected_impact, comparison_series,
  //   summary, assumptions } — the ONLY source of scenario results.
  runWhatIf: async (payload = {}) => {
    const data = await request("/intelligence/what-if/run", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  listScenarios: async (params = {}) => {
    const data = await request(`/intelligence/what-if/scenarios${intelQuery(params)}`);
    return { success: true, data: data?.data || data?.items || [] };
  },

  saveScenario: async (payload = {}) => {
    const data = await request("/intelligence/what-if/scenarios", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  // ---- Saved analyses ----
  listAnalyses: async (params = {}) => {
    const data = await request(`/intelligence/analyses${intelQuery(params)}`);
    return {
      success: true,
      data: data?.data || data?.items || [],
      total: data?.total ?? data?.count ?? null,
    };
  },

  saveAnalysis: async (payload = {}) => {
    const data = await request("/intelligence/analyses", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  // ---- Reports ----
  listReports: async (params = {}) => {
    const data = await request(`/intelligence/reports${intelQuery(params)}`);
    return { success: true, data: data?.data || data?.items || [] };
  },

  listReportTemplates: async () => {
    const data = await request("/intelligence/reports/templates");
    return { success: true, data: data?.data || data?.items || [] };
  },

  // POST /api/intelligence/reports/generate { name, description, date_range,
  //   sections, template } -> { report_url | html | ... } used by Generate PDF.
  generateReport: async (payload = {}) => {
    const data = await request("/intelligence/reports/generate", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  saveReportTemplate: async (payload = {}) => {
    const data = await request("/intelligence/reports/templates", {
      method: "POST",
      body: JSON.stringify(payload || {}),
    });
    return { success: true, data: data?.data || data || {} };
  },

  deleteAnalysis: async (id) => {
    const data = await request(`/intelligence/analyses/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return { success: true, data: data?.data || data || {} };
  },

  deleteScenario: async (id) => {
    const data = await request(`/intelligence/what-if/scenarios/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return { success: true, data: data?.data || data || {} };
  },

  deleteReport: async (id) => {
    const data = await request(`/intelligence/reports/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
    return { success: true, data: data?.data || data || {} };
  },

  getReport: async (id) => {
    const data = await request(`/intelligence/reports/${encodeURIComponent(id)}`);
    return { success: true, data: data?.data || data || {} };
  },

  // ---- Coverage (which datasets/metrics the module can reason about) ----
  getCoverage: async () => {
    const data = await request("/intelligence/coverage");
    return { success: true, data: data?.data || data || {} };
  },
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
    return { success: false, message: error?.message || "Feedback could not be sent." };
  }
};
