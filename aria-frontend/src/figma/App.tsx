import { createContext, useContext, useState, useEffect, useRef } from "react";
import "./index.css";
import "../aria-enhance.css";
import AppShell from "./components/AppShell";
import Login from "./pages/Login";
import LLMSelection from "./pages/LLMSelection";
import Dashboard from "./pages/Dashboard";
import AIAnalytics from "./pages/AIAnalytics";
import Insights from "./pages/Insights";
import Predictive from "./pages/Predictive";
import Prescription from "./pages/Prescription";
import Hypothesis from "./pages/Hypothesis";
import Data from "./pages/Data";
import Copilot from "./pages/Copilot";
import Documents from "./pages/Documents";
import History from "./pages/History";
import Settings from "./pages/Settings";
import {
  connectDatabase,
  fetchSchema,
  analyzeQuestion,
  generateAnalyticsResult,
  generateInsights,
  fetchSessionStatus,
} from "../services/api";
import {
  clearAuthSession,
  getAuthUser,
} from "../utils/authStorage";

export type Page =
  | "dashboard"
  | "analytics"
  | "insights"
  | "predictive"
  | "prescription"
  | "hypothesis"
  | "data"
  | "documents"
  | "copilot"
  | "history"
  | "settings";

type AppStage = "login" | "llm-selection" | "app";

interface ThemeCtx {
  isDark: boolean;
  toggleTheme: () => void;
  page: Page;
  setPage: (p: Page) => void;
}

export const ThemeContext = createContext<ThemeCtx>({
  isDark: false,
  toggleTheme: () => {},
  page: "dashboard",
  setPage: () => {},
});

export const useTheme = () => useContext(ThemeContext);

export default function App() {
  // ---- Auth stage ----
  const [appStage, setAppStage] = useState<AppStage>("login");
  const [currentUser, setCurrentUser] = useState<{ email?: string } | null>(null);
  const [selectedLLM, setSelectedLLM] = useState("");

  // ---- Theme ----
  const [isDark, setIsDark] = useState(() => {
    return localStorage.getItem("aria_theme") === "dark";
  });
  const [page, setPage] = useState<Page>("dashboard");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
    localStorage.setItem("aria_theme", isDark ? "dark" : "light");
  }, [isDark]);

  // Validate any stored session on mount: a stale localStorage token must not
  // skip login (audit BUG_REPORT 2026-09-07). Force login stage on 401.
  useEffect(() => {
    (async () => {
      const token = localStorage.getItem("aria_auth_token");
      if (!token) {
        setAppStage("login");
        return;
      }
      try {
        const res = await fetch("/api/session/status", {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.status === 401) {
          clearAuthSession();
          setCurrentUser(null);
          setAppStage("login");
        }
      } catch {
        // Offline/backend down: stay on login; do not trust the stored user.
        clearAuthSession();
        setCurrentUser(null);
        setAppStage("login");
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleTheme = () => setIsDark((d) => !d);

  // ---- Connection state ----
  const [connectionStatus, setConnectionStatus] = useState("not-connected");
  const [dbName, setDbName] = useState("");
  const [schemaData, setSchemaData] = useState<any>(null);
  const [schemaStatus, setSchemaStatus] = useState("idle");
  const [schemaError, setSchemaError] = useState("");
  const [connectionError, setConnectionError] = useState("");
  const [selectedSourceType, setSelectedSourceType] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  // ---- DB credentials ----
  const [dbHost, setDbHost] = useState("localhost");
  const [dbPort, setDbPort] = useState("5432");
  const [dbUsername, setDbUsername] = useState("postgres");
  const [dbPassword, setDbPassword] = useState("");

  // ---- Question / Query ----
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  // Cancel obsolete analyses when the user asks again (§25 performance).
  const askAbortRef = useRef<AbortController | null>(null);
  const [questionSuggestions, setQuestionSuggestions] = useState<string[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);

  // ---- Goal Agent ----
  const [goalStatus, setGoalStatus] = useState("idle");
  const [goalResult, setGoalResult] = useState<any>(null);
  const [goalError, setGoalError] = useState("");
  const [analysisResult, setAnalysisResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  // ---- Insight Agent ----
  const [insightStatus, setInsightStatus] = useState("idle");
  const [insightResult, setInsightResult] = useState<any>(null);
  const [insightError, setInsightError] = useState("");

  // ---- History ----
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [currentHistorySessionId, setCurrentHistorySessionId] = useState<string | null>(null);

  // =========================================================
  // AUTH HANDLERS
  // =========================================================

  const handleLogin = () => {
    const user = getAuthUser();
    setCurrentUser(user ? { email: user.email || user.username } : { email: "user" });
    setAppStage("llm-selection");
  };

  const handleLLMSelect = (mode: string) => {
    setSelectedLLM(mode);
    localStorage.setItem("aria_llm_mode", mode);
    // Restore connection state from the stored session so the Dashboard
    // shows KPIs/charts without requiring a fresh connect.
    (async () => {
      const result = await fetchSessionStatus();
      if (result.success && result.data) {
        if (result.data.connection_status === "connected") {
          setConnectionStatus("connected");
          setDbName(result.data.db_name || "");
          setSelectedSourceType(result.data.source_type || "relational");
          // Load schema from the server when reconnecting so the Data
          // section never shows "pending" — the DB was never disconnected.
          // Load schema directly (skip extraction) when reconnecting so the
          // Data section never shows "pending" — the DB was never disconnected.
          try {
            const token = localStorage.getItem("aria_auth_token");
            const res = await fetch("/api/schema", {
              headers: { Authorization: `Bearer ${token || ""}` },
            });
            const schemaJson = await res.json();
            if (res.ok && schemaJson?.ok && schemaJson.schema) {
              setSchemaData(schemaJson.schema);
              setSchemaStatus("success");
            } else {
              setSchemaStatus("idle");
              setSchemaData(null);
            }
          } catch {
            setSchemaStatus("idle");
            setSchemaData(null);
          }
        }
      }
    })();
    setAppStage("app");
  };

  const handleSignOut = () => {
    clearAuthSession();
    setCurrentUser(null);
    setSelectedLLM("");
    setAppStage("login");
    setConnectionStatus("not-connected");
    setDbName("");
    setSchemaData(null);
    setGoalResult(null);
    setAnalysisResult(null);
    setInsightResult(null);
    setQuestion("");
    setSubmittedQuestion("");
    setPage("dashboard");
  };

  // =========================================================
  // CONNECTION HANDLER
  // =========================================================

  const handleConnect = async (details: any) => {
    setConnectionError("");
    try {
      const result = await connectDatabase(details);
      if (result?.success) {
        setConnectionStatus("connected");
        setDbName(result?.data?.database || details?.db || "");
        setSelectedSourceType("relational");
        // Auto-fetch schema after connect
        await handleSchemaFetch();
      } else {
        setConnectionError(result?.message || "Connection failed");
      }
    } catch (err: any) {
      setConnectionError(err?.message || "Connection failed");
    }
  };

  const handleDisconnect = () => {
    setConnectionStatus("not-connected");
    setDbName("");
    setSchemaData(null);
    setSchemaStatus("idle");
  };

  const handleSchemaFetch = async () => {
    setSchemaStatus("loading");
    setSchemaError("");
    try {
      const result = await fetchSchema();
      if (result?.success) {
        setSchemaData(result?.data || null);
        setSchemaStatus("success");
      } else {
        setSchemaError("Failed to fetch schema");
        setSchemaStatus("error");
      }
    } catch (err: any) {
      setSchemaError(err?.message || "Schema fetch failed");
      setSchemaStatus("error");
    }
  };

  // =========================================================
  // FILE UPLOAD HANDLER
  // =========================================================

  const handleFileUpload = async (sourceType: string) => {
    const file = selectedFile;
    if (!file) return;
    setConnectionError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("provider", selectedLLM || "local");
      
      const token = localStorage.getItem("aria_auth_token");
      let url = sourceType === 'csv' ? '/api/connect_file' : (sourceType === 'pdf' ? '/api/connect_pdf' : `/api/connect_${sourceType}`);
      const res = await fetch(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      const data = await res.json();
      if (data.ok) {
        // After successful file connect, fetch schema and mark connected
        await handleSchemaFetch();
        setConnectionStatus("connected");
        setDbName(data?.table || data?.file || file.name.replace(/\.[^.]+$/, ""));
        setSelectedSourceType(data?.source_type || "semi-structured");
      } else {
        setConnectionError(data?.message || "File upload failed");
      }
    } catch (err: any) {
      setConnectionError(err?.message || "File upload failed");
    }
  };

  const handleAsk = async (q: string) => {
    if (!q?.trim()) return;
    // Abort any in-flight analysis before starting a new one.
    askAbortRef.current?.abort();
    const controller = new AbortController();
    askAbortRef.current = controller;
    setLoading(true);
    setGoalStatus("loading");
    setSubmittedQuestion(q);
    setGoalResult(null);
    setGoalError("");
    setInsightResult(null);
    try {
      // Pass multi-turn context when available (follow-up questions)
      const multiTurnContext = goalResult?.generatedSql && submittedQuestion
        ? { previousGoal: submittedQuestion, previousResult: { data: goalResult?.data || [], columns: goalResult?.processedDataSummary?.columns || [], data_selection: goalResult?.data_selection }, conversationId: goalResult?.conversationId }
        : goalResult?.conversationId ? { conversationId: goalResult.conversationId } : null;
      const result = await analyzeQuestion(q, selectedLLM, {
        sourceType: selectedSourceType,
        dbName,
      }, multiTurnContext, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (result?.success) {
        setGoalResult(result?.data || null);
        setGoalStatus("success");
        const analytics = await generateAnalyticsResult(result?.data);
        if (controller.signal.aborted) return;
        setAnalysisResult(analytics?.data || null);
      } else {
        setGoalStatus("error");
        setGoalError(result?.message || "Analysis failed");
      }
    } catch (err: any) {
      if (err?.name === "AbortError" || controller.signal.aborted) {
        setGoalStatus("idle");
        return;
      }
      setGoalStatus("error");
      setGoalError(err?.message || "Analysis failed");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      else setLoading(false);
    }
  };

  // =========================================================
  // INSIGHT HANDLER
  // =========================================================

  const handleInsightRetry = async () => {
    setInsightStatus("loading");
    setInsightError("");
    try {
      const result = await generateInsights(goalResult, analysisResult);
      if (result?.success) {
        setInsightResult(result?.data || null);
        setInsightStatus("success");
      } else {
        setInsightStatus("error");
        setInsightError(result?.message || "Insight generation failed");
      }
    } catch (err: any) {
      setInsightStatus("error");
      setInsightError(err?.message || "Insight generation failed");
    }
  };

  // =========================================================
  // HISTORY HANDLER
  // =========================================================

  // Reopen a history entry WITH its result/context (t.txt section 10),
  // not just the question text. Falls back to question-only on failure.
  const handleOpenHistory = async (session: any) => {
    if (!session) return;
    const questionText = session.goal || session.title || "";
    setSubmittedQuestion(questionText);
    setQuestion(questionText);
    const id = session.id;
    if (id) {
      try {
        const token = localStorage.getItem("aria_auth_token");
        const res = await fetch(`/api/history/${id}`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        const data = await res.json();
        const rec = data?.record;
        if (res.ok && rec) {
          const proc = rec.processed || {};
          setGoalResult({
            interpretedGoal: rec.goal || questionText,
            goalType: "analysis",
            clarificationRequired: false,
            clarificationMessage: "",
            relevantTables: proc?.data_selection?.tables || [],
            joinPlan: proc?.join_path || [],
            generatedSql: rec.sql_used || proc?.sql_used || proc?.sql || "",
            preprocessing: [],
            processedDataSummary: {
              rowCount: rec.row_count ?? 0,
              columns: rec.columns || [],
            },
            nextAgent: "Insight Agent",
            data: proc?.data || [],
            message: proc?.message || "",
            warnings: proc?.warnings || [],
            proactiveInsights: [],
            anomalies: [],
            dataQualityWarnings: [],
            explanation: null,
            confidence: "high",
            historyId: rec.id,
            suggestedQuestions: proc?.suggested_questions || [],
            provenance: null,
            conversationId: null,
            turnNumber: null,
          });
          setGoalStatus("success");
          const analytics = await generateAnalyticsResult({ data: proc?.data || [] });
          setAnalysisResult(analytics?.data || null);
        }
      } catch {
        // question-only restore below
      }
    }
    setPage("analytics");
  };

  const handleDeleteHistory = (_id: string) => {
    setHistoryRefreshKey((k) => k + 1);
  };

  // =========================================================
  // SCREENS
  // =========================================================

  if (appStage === "login") {
    return <Login onLogin={handleLogin} />;
  }

  if (appStage === "llm-selection") {
    return <LLMSelection onSelectLLM={handleLLMSelect} />;
  }

  return (
    <ThemeContext.Provider value={{ isDark, toggleTheme, page, setPage }}>
      <AppShell
        user={currentUser}
        selectedLLM={selectedLLM}
        dbName={dbName}
        onChangeLLM={() => setAppStage("llm-selection")}
        onSignOut={handleSignOut}
      >
        {(() => {
          switch (page) {
            case "dashboard":
              return (
                <Dashboard
                  setPage={setPage}
                  onAsk={handleAsk}
                  user={currentUser}
                  connectionStatus={connectionStatus}
                  dbName={dbName}
                  insightResult={insightResult}
                  analysisResult={analysisResult}
                  connectionError={connectionError}
                />
              );
            case "analytics":
              return (
                <AIAnalytics
                  initialQuery={question}
                  onAsk={handleAsk}
                  analysisResult={analysisResult}
                  goalStatus={goalStatus}
                  goalResult={goalResult}
                  goalError={goalError}
                  loading={loading}
                />
              );
            case "insights":
              return (
                <Insights
                  insightResult={insightResult}
                  insightStatus={insightStatus}
                  insightError={insightError}
                  onAskQuestion={(q) => { handleAsk(q); setPage("analytics"); }}
                />
              );
            case "predictive":
              return <Predictive insightResult={insightResult} goalResult={goalResult} />;
            case "prescription":
              return (
                <Prescription
                  insightResult={insightResult}
                  onAskQuestion={(q) => { handleAsk(q); setPage("analytics"); }}
                />
              );
            case "hypothesis":
              return (
                <Hypothesis
                  insightResult={insightResult}
                  onAskQuestion={(q) => { handleAsk(q); setPage("analytics"); }}
                />
              );
            case "data":
              return (
                <Data
                  connectionStatus={connectionStatus}
                  selectedSourceType={selectedSourceType}
                  dbName={dbName}
                  schemaData={schemaData}
                  schemaStatus={schemaStatus}
                  schemaError={schemaError}
                  onConnect={handleConnect}
                  onDisconnect={handleDisconnect}
                  onSchemaRetry={handleSchemaFetch}
                  onSourceTypeSelect={(t: string) => setSelectedSourceType(t)}
                  selectedFile={selectedFile}
                  onFileSelect={(f: File) => setSelectedFile(f)}
                  onFileUpload={(st?: string) => handleFileUpload(st || selectedSourceType || "csv")}
                  dbHost={dbHost}
                  dbPort={dbPort}
                  dbUsername={dbUsername}
                  dbPassword={dbPassword}
                  setDbHost={setDbHost}
                  setDbPort={setDbPort}
                  setDbName={setDbName}
                  setDbUsername={setDbUsername}
                  setDbPassword={setDbPassword}
                  connectionError={connectionError}
                />
              );
            case "documents":
              return <Documents />;
            case "copilot":
              return <Copilot analysisResult={analysisResult} goalResult={goalResult} />;
            case "history":
              return (
                <History
                  historyRefreshKey={historyRefreshKey}
                  onOpenHistory={handleOpenHistory}
                  onDeleteHistory={handleDeleteHistory}
                />
              );
            case "settings":
              return (
                <Settings
                  selectedLLM={selectedLLM}
                  onChangeLLM={() => setAppStage("llm-selection")}
                  user={currentUser}
                  connectionStatus={connectionStatus}
                  dbName={dbName}
                  selectedSourceType={selectedSourceType}
                />
              );
            default:
              return null;
          }
        })()}
      </AppShell>
    </ThemeContext.Provider>
  );
}
