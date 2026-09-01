import { useEffect, useState } from "react";
import "./App.css";
import "./aria-enhance.css";

// ================= PAGES =================
import Login from "./pages/Login";
import Register from "./pages/Register";
import LLMSelection from "./pages/LLMSelection";
import Dashboard from "./pages/Dashboard";
import AskARIA from "./pages/AskARIA";
import DataSource from "./pages/Datasource";
import Schema from "./pages/Schema";
import History from "./pages/History";
import SavedReports from "./pages/SavedReports";
import Documents from "./pages/Documents";
// ================= COMPONENTS =================
import Sidebar from "./components/Sidebar";
import AppHeader from "./components/AppHeader";
import Copilot from "./components/Copilot";
import Help from "./pages/Help";
import { useToast } from "./components/Toast";

// ================= API SERVICE =================
import {
  connectDatabase,
  connectFile,
  connectPdf,
  fetchSchema,
  getQuestionSuggestions,
  analyzeQuestion,
  generateAnalyticsResult,
  generateInsights,
  submitFeedback,
} from "./services/api";

import {
  addHistorySession,
  updateHistorySession,
  deleteHistorySession,
} from "./utils/historyStorage";

import { clearAuthSession } from "./utils/authStorage";

const LLM_MODE_STORAGE_KEY = "aria_llm_mode";

function App() {
  const toast = useToast();

  // =========================================================
  // APPLICATION FLOW
  // =========================================================

  const [appStage, setAppStage] = useState("login");

  const [theme, setTheme] = useState("light");
  const [currentUser, setCurrentUser] = useState(null);

  // =========================================================
  // RESTORE AUTH SESSION FROM LOCALSTORAGE ON MOUNT
  // =========================================================
  queueMicrotask(() => {
      const token = localStorage.getItem("aria_auth_token");
      const userStr = localStorage.getItem("aria_auth_user");

      if (token && userStr) {
        try {
          const user = JSON.parse(userStr);
          setCurrentUser(user);
          if (user && user.username) {
            setAppStage("app");
          }
        } catch {
          localStorage.removeItem("aria_auth_token");
          localStorage.removeItem("aria_auth_user");
        }
      }

      // Restore theme preference from localStorage
      const savedTheme = localStorage.getItem("aria_theme");
      if (savedTheme) {
        setTheme(savedTheme);
      }
    });

    // Apply saved theme and listen for system changes
    useEffect(() => {
      // Apply initial theme
      const root = document.documentElement;
      if (theme === "dark") {
        root.classList.add("dark-theme");
        root.classList.remove("light-theme");
      } else {
        root.classList.add("light-theme");
        root.classList.remove("dark-theme");
      }

      // Listen for changes
      const preferences = window.matchMedia("(prefers-color-scheme: dark)");
      const handleChange = (mediaQuery) => {
        if (!localStorage.getItem("aria_theme")) {
          // Only auto-switch if user hasn't set a preference
          setTheme(mediaQuery.matches ? "dark" : "light");
          if (mediaQuery.matches) {
            root.classList.add("dark-theme");
            root.classList.remove("light-theme");
          } else {
            root.classList.add("light-theme");
            root.classList.remove("dark-theme");
          }
        }
      };

      handleChange(preferences);
      preferences.addEventListener("change", handleChange);

      return () => {
        preferences.removeEventListener("change", handleChange);
      };
    }, [theme]);

  const [selectedLLM, setSelectedLLM] = useState("");

  // =========================================================
  // NAVIGATION
  // =========================================================

  const [activePage, setActivePage] = useState("askAria");

  // =========================================================
  // MOBILE NAVIGATION
  // =========================================================

  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const handlePageChange = (page) => {
    setActivePage(page);

    setMobileMenuOpen(false);
  };

  // =========================================================
  // ARIA COPILOT (drawer shell — uses the existing pipeline)
  // =========================================================

  const [copilotOpen, setCopilotOpen] = useState(false);

  const [copilotBusy, setCopilotBusy] = useState(false);

  const [copilotSuggestions, setCopilotSuggestions] = useState([]);

  // =========================================================
  // DASHBOARD STATES
  // =========================================================

  const [question, setQuestion] = useState("");

  const [submittedQuestion, setSubmittedQuestion] = useState("");

  const [loading, setLoading] = useState(false);

  const [analysisResult, setAnalysisResult] = useState(null);

  // =========================================================
  // GOAL AGENT STATES
  // =========================================================

  const [questionSuggestions, setQuestionSuggestions] = useState([]);

  const [suggestionsLoading, setSuggestionsLoading] = useState(false);

  const [goalStatus, setGoalStatus] = useState("idle");

  const [goalResult, setGoalResult] = useState(null);

  const [goalError, setGoalError] = useState("");

  // =========================================================
  // INSIGHT AGENT STATES
  // =========================================================

  const [insightStatus, setInsightStatus] = useState("idle");

  const [insightResult, setInsightResult] = useState(null);

  const [insightError, setInsightError] = useState("");
  // =========================================================
  // DAY 8 - FEEDBACK AGENT STATES
  // =========================================================

  const [feedbackStatus, setFeedbackStatus] = useState("idle");

  const [submittedFeedback, setSubmittedFeedback] = useState(null);

  const [feedbackError, setFeedbackError] = useState("");

  // =========================================================
  // DAY 9 - HISTORY STATES
  // =========================================================

  const [currentHistorySessionId, setCurrentHistorySessionId] = useState(null);

  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  // =========================================================
  // DATA SOURCE STATES
  // =========================================================

  const [selectedSourceType, setSelectedSourceType] = useState("");

  const [selectedFile, setSelectedFile] = useState(null);

  const [connectionStatus, setConnectionStatus] = useState("not-connected");

  const [connectionError, setConnectionError] = useState("");

  // =========================================================
  // DATABASE STATES
  // =========================================================

  const [dbHost, setDbHost] = useState("localhost");

  const [dbPort, setDbPort] = useState("5432");

  const [dbName, setDbName] = useState("northwind");

  const [dbUsername, setDbUsername] = useState("postgres");

  const [dbPassword, setDbPassword] = useState("");

  // =========================================================
  // SCHEMA AGENT STATES
  // =========================================================

  const [schemaStatus, setSchemaStatus] = useState("idle");

  const [schemaData, setSchemaData] = useState(null);

  const [schemaError, setSchemaError] = useState("");

  // =========================================================
  // RESET SCHEMA AGENT
  // =========================================================

  const resetSchemaAgent = () => {
    setSchemaStatus("idle");
    setSchemaData(null);
    setSchemaError("");
  };

  // =========================================================
  // RESET GOAL AGENT
  // =========================================================

  const resetGoalAgent = () => {
    setGoalStatus("idle");
    setGoalResult(null);
    setGoalError("");
    setQuestionSuggestions([]);
    setSuggestionsLoading(false);
  };

  // =========================================================
  // RESET INSIGHT AGENT
  // =========================================================

  const resetInsightAgent = () => {
    setInsightStatus("idle");
    setInsightResult(null);
    setInsightError("");
  };

  // =========================================================
  // DAY 8 - RESET FEEDBACK AGENT
  // =========================================================

  const resetFeedbackAgent = () => {
    setFeedbackStatus("idle");
    setSubmittedFeedback(null);
    setFeedbackError("");
  };

  // =========================================================
  // NEW QUESTION
  // =========================================================
  //
  // When the user starts typing another question,
  // remove the previous Goal Agent, analytics,
  // and Insight Agent results.
  // =========================================================

  const handleQuestionChange = (newQuestion) => {
    setQuestion(newQuestion);

    setSubmittedQuestion("");

    setAnalysisResult(null);

    setGoalStatus("idle");

    setGoalResult(null);

    setGoalError("");

    resetInsightAgent();

    resetFeedbackAgent();

    setCurrentHistorySessionId(null);
  };

  // =========================================================
  // RUN SCHEMA AGENT
  // =========================================================

  const runSchemaAgent = async () => {
    setSchemaStatus("running");
    setSchemaData(null);
    setSchemaError("");

    try {
      const response = await fetchSchema();

      if (!response?.success || !response?.data) {
        throw new Error("The Schema Agent did not return valid schema data.");
      }

      setSchemaData(response.data);

      setSchemaStatus("success");

      setSchemaError("");
    } catch (error) {
      console.error("Schema Agent error:", error);

      setSchemaData(null);

      setSchemaStatus("failed");

      setSchemaError(
        error?.message || "ARIA could not analyze the connected data source.",
      );
    }
  };

  // =========================================================
  // DATASET-AWARE QUESTION SUGGESTIONS
  // =========================================================

  useEffect(() => {
    let isCancelled = false;

    if (connectionStatus !== "connected" || schemaStatus !== "success") {
      queueMicrotask(() => setCopilotSuggestions([]));

      return;
    }

    const suggestionTimer = setTimeout(async () => {
      setSuggestionsLoading(true);

      try {
        const response = await getQuestionSuggestions(question, {
          sourceType: selectedSourceType,

          databaseName: dbName,
        });

        if (!isCancelled) {
          setQuestionSuggestions(response?.data || []);

          setCopilotSuggestions(response?.data || []);
        }
      } catch (error) {
        console.error("Suggestion error:", error);

        if (!isCancelled) {
          setQuestionSuggestions([]);

          setCopilotSuggestions([]);
        }
      } finally {
        if (!isCancelled) {
          setSuggestionsLoading(false);
        }
      }
    }, 250);

    return () => {
      isCancelled = true;

      clearTimeout(suggestionTimer);
    };
  }, [question, connectionStatus, schemaStatus, selectedSourceType, dbName]);

  // =========================================================
  // SELECT QUESTION SUGGESTION
  // =========================================================

  const handleSuggestionSelect = (suggestion) => {
    handleQuestionChange(suggestion);

    setQuestionSuggestions([]);
  };

  // =========================================================
  // LOGIN
  // =========================================================

  const [dbConfigured, setDbConfigured] = useState(false);

  const handleLogin = (userData) => {
    setCurrentUser(userData);

    setAppStage("llm-selection");
  };

  // Check if database is already configured from localStorage
  useEffect(() => {
    const configured = localStorage.getItem("aria_db_configured");
    if (configured === "true") {
      setDbConfigured(true);
    }
  }, []);

  // =========================================================
  // CREATE ACCOUNT
  // =========================================================

  const handleCreateAccount = () => {
    setAppStage("register");
  };

  // =========================================================
  // RETURN TO LOGIN
  // =========================================================

  const handleBackToLogin = () => {
    setAppStage("login");
  };

  // =========================================================
  // LLM SELECTION
  // =========================================================

  const handleLLMSelect = (mode) => {
    setSelectedLLM(mode);

    localStorage.setItem(LLM_MODE_STORAGE_KEY, mode);

    if (dbConfigured) {
      setActivePage("dashboard");
    } else {
      setActivePage("dataSource");
    }

    setMobileMenuOpen(false);

    setAppStage("app");

    localStorage.setItem("aria_db_configured", "true");
    setDbConfigured(true);
  };

  // =========================================================
  // CHANGE AI MODE
  // =========================================================

  const handleChangeLLM = () => {
    setMobileMenuOpen(false);

    setCopilotOpen(false);

    resetInsightAgent();

    setSelectedLLM("");

    localStorage.setItem(LLM_MODE_STORAGE_KEY, "");

    setAppStage("llm-selection");
  };

  // =========================================================
  // SIGN OUT
  // =========================================================

  const handleSignOut = () => {
    setMobileMenuOpen(false);

    setCopilotOpen(false);

    setCopilotSuggestions([]);

    setCurrentUser(null);

    setSelectedLLM("");

    localStorage.setItem(LLM_MODE_STORAGE_KEY, "");

    clearAuthSession();

    setAppStage("login");

    setActivePage("dashboard");

    setQuestion("");

    setSubmittedQuestion("");

    setAnalysisResult(null);

    setLoading(false);

    setSelectedSourceType("");

    setSelectedFile(null);

    setConnectionStatus("not-connected");

    setConnectionError("");

    setDbHost("localhost");

    setDbPort("5432");

    setDbName("northwind");

    setDbUsername("postgres");

    setDbPassword("");

    resetSchemaAgent();

    resetGoalAgent();

    resetInsightAgent();
  };

  // =========================================================
  // DATA SOURCE TYPE SELECTION
  // =========================================================

  const handleSourceTypeSelect = (sourceType) => {
    if (connectionStatus === "connecting") {
      return;
    }

    setSelectedSourceType(sourceType);

    setSelectedFile(null);

    setConnectionStatus("not-connected");

    setConnectionError("");

    setDbPassword("");

    resetSchemaAgent();

    resetGoalAgent();

    resetInsightAgent();

    setQuestion("");

    setSubmittedQuestion("");

    setAnalysisResult(null);

    // PostgreSQL defaults
    if (sourceType === "postgresql") {
      setDbHost("localhost");

      setDbPort("5432");

      setDbName("northwind");

      setDbUsername("postgres");
    }

    // MySQL defaults
    if (sourceType === "mysql") {
      setDbHost("localhost");

      setDbPort("3306");

      setDbName("");

      setDbUsername("root");
    }
  };

  // =========================================================
  // FILE SELECTION
  // =========================================================

  const handleFileSelect = (event) => {
    const file = event.target.files?.[0];

    setConnectionError("");

    resetSchemaAgent();

    resetGoalAgent();

    resetInsightAgent();

    setAnalysisResult(null);

    setSubmittedQuestion("");

    if (!file) {
      setSelectedFile(null);

      return;
    }

    const fileName = file.name.toLowerCase();

    // CSV validation
    if (selectedSourceType === "csv" && !fileName.endsWith(".csv")) {
      setSelectedFile(null);

      setConnectionStatus("failed");

      setConnectionError("Please select a valid CSV file.");

      return;
    }

    // PDF validation
    if (selectedSourceType === "pdf" && !fileName.endsWith(".pdf")) {
      setSelectedFile(null);

      setConnectionStatus("failed");

      setConnectionError("Please select a valid PDF document.");

      return;
    }

    setSelectedFile(file);

    setConnectionStatus("not-connected");

    setConnectionError("");
  };

  // =========================================================
  // FILE UPLOAD
  // =========================================================

  const handleFileUpload = async () => {
    setConnectionError("");

    resetSchemaAgent();

    resetGoalAgent();

    resetInsightAgent();

    setAnalysisResult(null);

    if (!selectedFile) {
      setConnectionStatus("failed");

      setConnectionError(
        selectedSourceType === "pdf"
          ? "Please select a PDF document first."
          : "Please select a CSV file first.",
      );

      return;
    }

    setConnectionStatus("connecting");

    try {
      let response;
      if (selectedSourceType === "pdf") {
        response = await connectPdf(selectedFile, selectedLLM || "local");
      } else {
        response = await connectFile(selectedFile, selectedLLM || "local");
      }

      if (!response?.success) {
        throw new Error(
          response?.message || "ARIA could not upload the selected file.",
        );
      }

      if (response.data?.table) {
        setDbName(response.data.table);
      }

      if (response.data?.document_id) {
        setDbName(response.data.document_id);
      }

      setConnectionStatus("connected");

      setConnectionError("");

      toast.success(selectedSourceType === "pdf" 
        ? "PDF uploaded successfully - processing started" 
        : "File uploaded successfully");

      if (selectedSourceType !== "pdf") {
        await runSchemaAgent();
      }
    } catch (error) {
      console.error("File upload error:", error);

      setConnectionStatus("failed");

      setConnectionError(
        error?.message || "ARIA could not process the uploaded file.",
      );

      toast.error("Could not upload the file");
    }
  };

  // =========================================================
  // DATABASE CONNECTION
  // =========================================================

  const handleDatabaseConnect = async () => {
    setConnectionError("");

    resetSchemaAgent();

    resetGoalAgent();

    resetInsightAgent();

    setAnalysisResult(null);

    // Host
    if (dbHost.trim() === "") {
      setConnectionStatus("failed");

      setConnectionError("Host is required.");

      return;
    }

    // Port
    if (dbPort.trim() === "") {
      setConnectionStatus("failed");

      setConnectionError("Port is required.");

      return;
    }

    // Database
    if (dbName.trim() === "") {
      setConnectionStatus("failed");

      setConnectionError("Database name is required.");

      return;
    }

    // Username
    if (dbUsername.trim() === "") {
      setConnectionStatus("failed");

      setConnectionError("Username is required.");

      return;
    }

    // Password
    if (dbPassword.trim() === "") {
      setConnectionStatus("failed");

      setConnectionError("Password is required.");

      return;
    }

    // Numeric port validation
    if (!/^\d+$/.test(dbPort)) {
      setConnectionStatus("failed");

      setConnectionError("Port must contain numbers only.");

      return;
    }

    setConnectionStatus("connecting");

    try {
      const response = await connectDatabase({
        provider: selectedLLM || "local",

        dbType: selectedSourceType,

        host: dbHost,

        port: dbPort,

        db: dbName,

        user: dbUsername,

        password: dbPassword,

        dbSchema: "public",
      });

      if (!response?.success) {
        throw new Error(
          response?.message || "ARIA could not connect to the database.",
        );
      }

      if (response.data?.database) {
        setDbName(response.data.database);
      }

      setConnectionStatus("connected");

      setConnectionError("");

      toast.success("Data source connected");

      await runSchemaAgent();
    } catch (error) {
      console.error("Database connection error:", error);

      setConnectionStatus("failed");

      setConnectionError(
        error?.message || "ARIA could not connect to the database.",
      );

      toast.error("Could not connect to the data source");
    }
  };

  // =========================================================
  // DISCONNECT DATA SOURCE
  // =========================================================

  const handleDataSourceDisconnect = () => {
    setConnectionStatus("not-connected");

    setConnectionError("");

    setSelectedFile(null);

    setDbPassword("");

    resetSchemaAgent();

    resetGoalAgent();

    resetInsightAgent();

    setQuestion("");

    setSubmittedQuestion("");

    setAnalysisResult(null);

    toast.info("Data source disconnected");
  };

  // =========================================================
  // RETRY SCHEMA AGENT
  // =========================================================

  const handleSchemaRetry = () => {
    if (connectionStatus !== "connected") {
      return;
    }

    resetGoalAgent();

    resetInsightAgent();

    setAnalysisResult(null);

    runSchemaAgent();
  };

  // =========================================================
  // QUICK ASK (Dashboard quick input → pre-fills Ask ARIA)
  // =========================================================

  const handleQuickAsk = (questionText) => {
    const text = String(questionText || "").trim();

    if (text) {
      setQuestion(text);
    }

    setCopilotOpen(false);

    setActivePage("askAria");

    setMobileMenuOpen(false);
  };

  // =========================================================
  // COPILOT PIPELINE
  // =========================================================
  //
  // The Copilot is a presentation layer only. It runs the SAME
  // backend pipeline as the Ask ARIA page: Goal Agent (/api/ask)
  // → analytics builder → Insight Agent (/api/insight).
  // =========================================================

  const handleCopilotAsk = async (questionText) => {
    if (connectionStatus !== "connected") {
      throw new Error("Connect or upload a data source first.");
    }

    if (schemaStatus !== "success") {
      throw new Error(
        "The Schema Agent is still analyzing the connected data. Please try again in a moment.",
      );
    }

    const text = String(questionText || "").trim();

    if (text === "") {
      throw new Error("Please ask a business question.");
    }

    setCopilotBusy(true);

    try {
      // STEP 1 - GOAL AGENT
      const response = await analyzeQuestion(text, selectedLLM, {
        sourceType: selectedSourceType,

        databaseName: dbName,

        schema: schemaData,
      });

      if (!response?.success || !response?.data) {
        throw new Error("The Goal Agent did not return a valid result.");
      }

      const goalData = response.data;

      if (goalData.clarificationRequired || !goalData.nextAgent) {
        return {
          submittedQuestion: text,
          goalData,
          analyticsData: null,
          insightData: null,
        };
      }

      // STEP 2 - ANALYTICS RESULT (KPIs / charts / table)
      const analyticsResponse = await generateAnalyticsResult(goalData);

      if (!analyticsResponse?.success) {
        throw new Error("Analytics result could not be generated.");
      }

      const analyticsData = analyticsResponse.data;

      // STEP 3 - INSIGHT AGENT
      const insightResponse = await generateInsights(goalData, analyticsData);

      if (!insightResponse?.success || !insightResponse?.data) {
        throw new Error("The Insight Agent did not return a valid result.");
      }

      const insightData = insightResponse.data;

      // Surface the result to the main workspace (visible behind the drawer)
      setSubmittedQuestion(text);

      setGoalResult(goalData);

      setGoalStatus("success");

      setAnalysisResult(analyticsData);

      setInsightResult(insightData);

      setInsightStatus("success");

      setInsightError("");

      // Auto-save to History (mirrors the Ask ARIA flow)
      const historySessionId = `aria-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;

      const historySession = {
        id: historySessionId,

        createdAt: new Date().toISOString(),

        userEmail: currentUser?.email || null,

        question: text,

        llmMode: selectedLLM,

        source: {
          type: selectedSourceType,

          name:
            selectedSourceType === "csv" || selectedSourceType === "pdf"
              ? selectedFile?.name || "Uploaded file"
              : dbName || "Connected database",
        },

        goal: goalData,

        analytics: analyticsData,

        insights: insightData,

        feedback: null,

        savedReport: false,
      };

      addHistorySession(historySession);

      setCurrentHistorySessionId(historySessionId);

      return {
        submittedQuestion: text,
        goalData,
        analyticsData,
        insightData,
      };
    } finally {
      setCopilotBusy(false);
    }
  };

  // =========================================================
  // ANALYZE QUESTION
  // GOAL AGENT + DAY 6 ANALYTICS RESULT
  // =========================================================

  const handleAnalyze = async () => {
    // Data source required
    if (connectionStatus !== "connected") {
      alert("Please connect or upload a data source first.");

      return;
    }

    // Schema must be ready
    if (schemaStatus !== "success") {
      alert(
        "Please wait until the Schema Agent has completed before asking ARIA a question.",
      );

      return;
    }

    // Question required
    if (question.trim() === "") {
      alert("Please enter a business question.");

      return;
    }
    setActivePage("dashboard");
    setMobileMenuOpen(false);
    setLoading(true);

    setSubmittedQuestion("");

    setAnalysisResult(null);

    resetInsightAgent();

    setGoalStatus("running");

    setGoalResult(null);

    setGoalError("");

    setQuestionSuggestions([]);

    try {
      // =====================================================
      // STEP 1 - GOAL AGENT
      // =====================================================

      const response = await analyzeQuestion(question, selectedLLM, {
        sourceType: selectedSourceType,

        databaseName: dbName,

        schema: schemaData,
      });

      if (!response?.success || !response?.data) {
        throw new Error("The Goal Agent did not return a valid result.");
      }

      const goalData = response.data;

      setSubmittedQuestion(question);

      setGoalResult(goalData);

      setGoalStatus("success");

      // =====================================================
      // CLARIFICATION REQUIRED
      // =====================================================
      //
      // Do not generate analytics when the Goal Agent
      // does not have enough information.
      // =====================================================

      if (goalData.clarificationRequired || !goalData.nextAgent) {
        setAnalysisResult(null);

        resetInsightAgent();

        return;
      }

      // =====================================================
      // STEP 2 - DAY 6 ANALYTICS RESULT
      // =====================================================

      const analyticsResponse = await generateAnalyticsResult(goalData);

      if (!analyticsResponse?.success) {
        throw new Error("Analytics result could not be generated.");
      }

      const analyticsData = analyticsResponse.data;

      setAnalysisResult(analyticsData);

      // =====================================================
      // STEP 3 - INSIGHT AGENT
      // =====================================================

      setInsightStatus("running");

      setInsightResult(null);

      setInsightError("");

      try {
        const insightResponse = await generateInsights(goalData, analyticsData);

        if (!insightResponse?.success || !insightResponse?.data) {
          throw new Error("The Insight Agent did not return a valid result.");
        }
        // =====================================================
        // DAY 9 - AUTO SAVE COMPLETED ANALYSIS TO HISTORY
        // =====================================================

        if (!currentHistorySessionId) {
          const historySessionId = `aria-${Date.now()}-${Math.random()
            .toString(36)
            .slice(2, 8)}`;

          const historySession = {
            id: historySessionId,

            createdAt: new Date().toISOString(),

            userEmail: currentUser?.email || null,

            question: question,

            llmMode: selectedLLM,

            source: {
              type: selectedSourceType,

              name:
                selectedSourceType === "csv" || selectedSourceType === "pdf"
                  ? selectedFile?.name || "Uploaded file"
                  : dbName || "Connected database",
            },

            goal: goalData,

            analytics: analyticsData,

            insights: insightResponse.data,

            feedback: null,

            savedReport: false,
          };

          addHistorySession(historySession);

          setCurrentHistorySessionId(historySessionId);
        }
        setInsightResult(insightResponse.data);

        setInsightStatus("success");

        setInsightError("");

        toast.success("Analysis complete");
      } catch (insightAgentError) {
        console.error("Insight Agent error:", insightAgentError);

        setInsightStatus("failed");

        setInsightResult(null);

        setInsightError(
          insightAgentError?.message ||
            "ARIA could not generate insights from this analysis.",
        );
      }
    } catch (error) {
      console.error("ARIA analysis error:", error);

      setGoalStatus("failed");

      setGoalResult(null);

      setAnalysisResult(null);

      resetInsightAgent();

      setGoalError(
        error?.message || "ARIA could not process this business question.",
      );
    } finally {
      setLoading(false);
    }
  };
  // =========================================================
  // RETRY INSIGHT AGENT
  // =========================================================
  //
  // Retry only the Insight Agent.
  // Keep Goal Agent and analytics results unchanged.
  // =========================================================

  const handleInsightRetry = async () => {
    if (!goalResult || !analysisResult || insightStatus === "running") {
      return;
    }

    setInsightStatus("running");
    setInsightResult(null);
    setInsightError("");

    try {
      const insightResponse = await generateInsights(
        goalResult,
        analysisResult,
      );

      if (!insightResponse?.success || !insightResponse?.data) {
        throw new Error("The Insight Agent did not return a valid result.");
      }

      setInsightResult(insightResponse.data);

      setInsightStatus("success");

      setInsightError("");
    } catch (insightAgentError) {
      console.error("Insight Agent retry error:", insightAgentError);

      setInsightStatus("failed");

      setInsightResult(null);

      setInsightError(
        insightAgentError?.message ||
          "ARIA could not generate insights from this analysis.",
      );
    }
  };
  // =========================================================
  // DAY 8 - SUBMIT FEEDBACK
  // =========================================================

  const handleFeedbackSubmit = async (feedbackData) => {
    if (
      !submittedQuestion ||
      !goalResult ||
      !analysisResult ||
      !insightResult
    ) {
      return;
    }

    setFeedbackStatus("submitting");

    setFeedbackError("");

    try {
      const feedbackPayload = {
        question: submittedQuestion,

        goal: goalResult,

        analytics: analysisResult,

        insights: insightResult,

        feedback: feedbackData,
      };

      const response = await submitFeedback(feedbackPayload);

      if (!response?.success) {
        throw new Error("Feedback could not be submitted.");
      }

      setSubmittedFeedback(feedbackPayload);
      if (currentHistorySessionId) {
        updateHistorySession(currentHistorySessionId, {
          feedback: feedbackPayload,
        });
      }

      setFeedbackStatus("success");

      setFeedbackError("");
    } catch (error) {
      console.error("Feedback submission error:", error);

      setSubmittedFeedback(null);

      setFeedbackStatus("failed");

      setFeedbackError(
        error?.message || "ARIA could not submit your feedback.",
      );
    }
  };
  // =========================================================
  // DAY 9 - OPEN HISTORY SESSION
  // =========================================================

  const handleOpenHistorySession = (session) => {
    if (!session) {
      return;
    }

    // Restore question
    setQuestion(session.question || "");

    setSubmittedQuestion(session.question || "");

    // Restore Goal Agent
    setGoalResult(session.goal || null);

    setGoalStatus(session.goal ? "success" : "idle");

    setGoalError("");

    // Restore Analytics
    setAnalysisResult(session.analytics || null);

    // Restore Insight Agent
    setInsightResult(session.insights || null);

    setInsightStatus(session.insights ? "success" : "idle");

    setInsightError("");

    // Restore Feedback status
    setSubmittedFeedback(session.feedback || null);

    setFeedbackStatus(session.feedback ? "success" : "idle");

    setFeedbackError("");

    // Restore source information
    setSelectedSourceType(session.source?.type || "");

    if (
      session.source?.type === "postgresql" ||
      session.source?.type === "mysql"
    ) {
      setDbName(session.source?.name || "");
    }

    setConnectionStatus("connected");

    // Restore AI mode
    if (session.llmMode) {
      setSelectedLLM(session.llmMode);
    }

    // Remember which History record is open
    setCurrentHistorySessionId(session.id);

    // Clear temporary states
    setLoading(false);

    setQuestionSuggestions([]);

    // Return user to Dashboard
    setActivePage("dashboard");

    setMobileMenuOpen(false);
  };
  // =========================================================
  // DAY 9 - SAVE REPORT
  // =========================================================

  const handleSaveReport = (sessionId) => {
    if (!sessionId) {
      return;
    }

    updateHistorySession(sessionId, {
      savedReport: true,
      savedAt: new Date().toISOString(),
    });

    setHistoryRefreshKey((current) => current + 1);

    toast.success("Analysis saved to reports");
  };
  // =========================================================
  // DAY 9 - REMOVE SAVED REPORT
  // =========================================================

  const handleRemoveSavedReport = (sessionId) => {
    if (!sessionId) {
      return;
    }

    updateHistorySession(sessionId, {
      savedReport: false,
      savedAt: null,
    });

    setHistoryRefreshKey((current) => current + 1);

    toast.info("Removed from saved reports");
  };

  // =========================================================
  // DAY 9 - DELETE HISTORY SESSION
  // =========================================================

  const handleDeleteHistorySession = (sessionId) => {
    if (!sessionId) {
      return;
    }

    deleteHistorySession(sessionId);

    setHistoryRefreshKey((current) => current + 1);

    toast.info("Analysis deleted");
  };
  // =========================================================
  // LOGIN SCREEN
  // =========================================================

  if (appStage === "login") {
    return (
      <Login onLogin={handleLogin} onCreateAccount={handleCreateAccount} />
    );
  }

  // =========================================================
  // REGISTER SCREEN
  // =========================================================

  if (appStage === "register") {
    return <Register onBackToLogin={handleBackToLogin} />;
  }

  // =========================================================
  // LLM SELECTION SCREEN
  // =========================================================

  if (appStage === "llm-selection") {
    return <LLMSelection onSelectLLM={handleLLMSelect} />;
  }

  // =========================================================
  // MAIN APPLICATION
  // =========================================================

  return (
    <div className="app">
      {/* =====================================================
          MOBILE TOP BAR
      ====================================================== */}

      <header className="mobile-topbar">
        <div className="mobile-topbar-brand">
          <strong>ARIA</strong>

          <span className="mobile-llm-badge">
            {selectedLLM === "local"
              ? "Local LLM"
              : selectedLLM === "cloud"
                ? "Cloud LLM"
                : "AI Mode"}
          </span>

          <button
            className="theme-toggle-btn"
            onClick={() => setTheme((t) => (t === "light" ? "dark" : "light"))}
            aria-label={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
          >
            {theme === "dark" ? "☀" : "☾"}
          </button>
        </div>

        <button
          type="button"
          className="mobile-menu-button"
          onClick={() => setMobileMenuOpen((current) => !current)}
          aria-label={mobileMenuOpen ? "Close navigation" : "Open navigation"}
          aria-expanded={mobileMenuOpen}
        >
          {mobileMenuOpen ? "×" : "☰"}
        </button>
      </header>

      {/* =====================================================
          MOBILE SIDEBAR OVERLAY
      ====================================================== */}

      {mobileMenuOpen && (
        <button
          type="button"
          className="mobile-sidebar-overlay"
          aria-label="Close navigation"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      {/* =====================================================
          SIDEBAR
      ====================================================== */}

      <div className={`sidebar-shell ${mobileMenuOpen ? "open" : ""}`}>
        <Sidebar
          activePage={activePage}
          setActivePage={handlePageChange}
          selectedLLM={selectedLLM}
          currentUser={currentUser}
          handleChangeLLM={handleChangeLLM}
          handleSignOut={handleSignOut}
        />
      </div>

      <main className="main-content">
        <div className="content-width">
        <AppHeader
          activePage={activePage}
          selectedLLM={selectedLLM}
          currentUser={currentUser}
          handleChangeLLM={handleChangeLLM}
          handleSignOut={handleSignOut}
          onNavigate={handlePageChange}
          onOpenHistorySession={handleOpenHistorySession}
          theme={theme}
          setTheme={setTheme}
        />

        <div className="page-enter" key={activePage}>
        {/* ASK ARIA */}

        {activePage === "askAria" && (
          <AskARIA
            question={question}
            setQuestion={handleQuestionChange}
            loading={loading}
            handleAnalyze={handleAnalyze}
            connectionStatus={connectionStatus}
            dbName={dbName}
            selectedSourceType={selectedSourceType}
            selectedFile={selectedFile}
            questionSuggestions={questionSuggestions}
            suggestionsLoading={suggestionsLoading}
            handleSuggestionSelect={handleSuggestionSelect}
          />
        )}
        {/* DASHBOARD */}

        {activePage === "dashboard" && (
          <Dashboard
            key={submittedQuestion || "new-analysis"}
            submittedQuestion={submittedQuestion}
            analysisResult={analysisResult}
            connectionStatus={connectionStatus}
            dbName={dbName}
            selectedSourceType={selectedSourceType}
            selectedFile={selectedFile}
            schemaData={schemaData}
            handleSuggestionSelect={handleSuggestionSelect}
            handleSaveReport={handleSaveReport}
            currentHistorySessionId={currentHistorySessionId}
            goalStatus={goalStatus}
            goalResult={goalResult}
            goalError={goalError}
            insightStatus={insightStatus}
            insightResult={insightResult}
            insightError={insightError}
            handleInsightRetry={handleInsightRetry}
            feedbackStatus={feedbackStatus}
            submittedFeedback={submittedFeedback}
            feedbackError={feedbackError}
            handleFeedbackSubmit={handleFeedbackSubmit}
            onQuickAsk={handleQuickAsk}
            onNavigate={handlePageChange}
            onRetry={handleAnalyze}
            currentUser={currentUser}
          />
        )}

        {/* DATA SOURCE */}

        {activePage === "dataSource" && (
          <DataSource
            selectedSourceType={selectedSourceType}
            handleSourceTypeSelect={handleSourceTypeSelect}
            selectedFile={selectedFile}
            handleFileSelect={handleFileSelect}
            dbHost={dbHost}
            setDbHost={setDbHost}
            dbPort={dbPort}
            setDbPort={setDbPort}
            dbName={dbName}
            setDbName={setDbName}
            dbUsername={dbUsername}
            setDbUsername={setDbUsername}
            dbPassword={dbPassword}
            setDbPassword={setDbPassword}
            connectionStatus={connectionStatus}
            connectionError={connectionError}
            handleDatabaseConnect={handleDatabaseConnect}
            handleFileUpload={handleFileUpload}
            handleDataSourceDisconnect={handleDataSourceDisconnect}
            onClose={() => setActivePage("history")}
            currentUser={currentUser}
            onNavigate={handlePageChange}
          />
        )}

        {/* SCHEMA */}

        {activePage === "schema" && (
          <Schema
            connectionStatus={connectionStatus}
            selectedSourceType={selectedSourceType}
            selectedFile={selectedFile}
            dbName={dbName}
            schemaStatus={schemaStatus}
            schemaData={schemaData}
            schemaError={schemaError}
            handleSchemaRetry={handleSchemaRetry}
          />
        )}
        {/* HISTORY */}

        {activePage === "history" && (
          <History
            currentUser={currentUser}
            handleOpenHistorySession={handleOpenHistorySession}
            handleSaveReport={handleSaveReport}
            historyRefreshKey={historyRefreshKey}
            handleDeleteHistorySession={handleDeleteHistorySession}
            onNavigate={handlePageChange}
          />
        )}
        {/* SAVED REPORTS */}

        {activePage === "savedReports" && (
          <SavedReports
            currentUser={currentUser}
            handleOpenHistorySession={handleOpenHistorySession}
            handleRemoveSavedReport={handleRemoveSavedReport}
          />
        )}
        {/* HELP & SUPPORT */}

        {activePage === "help" && <Help />}
        {/* DOCUMENTS */}
        {activePage === "documents" && (
          <Documents
            currentUser={currentUser}
            onNavigate={handlePageChange}
          />
        )}
        </div>
        </div>
      </main>

      {/* =====================================================
          ARIA COPILOT (overlay drawer — existing Ask ARIA flow)
      ====================================================== */}

      <Copilot
        key={currentUser?.email || "anon"}
        open={copilotOpen}
        setOpen={setCopilotOpen}
        onAsk={handleCopilotAsk}
        processing={loading || copilotBusy}
        connectionReady={connectionStatus === "connected"}
        schemaReady={schemaStatus === "success"}
        suggestions={copilotSuggestions}
        activePage={activePage}
        hasResult={Boolean(
          submittedQuestion && goalResult && analysisResult && insightResult,
        )}
        onNavigate={(page) => {
          setCopilotOpen(false);

          setMobileMenuOpen(false);

          setActivePage(page);
        }}
      />
    </div>
  );
}

export default App;
