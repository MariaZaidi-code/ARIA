import { createContext, useContext, useState, useEffect } from "react";
import "./index.css";
import AppShell from "./components/AppShell";
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

interface ThemeCtx {
  isDark: boolean;
  toggleTheme: () => void;
  page: Page;
  setPage: (p: Page) => void;
}

interface AppProps {
  // User & Auth
  user?: { email?: string } | null;
  selectedLLM?: string;
  onChangeLLM?: () => void;
  onSignOut?: () => void;

  // Connection & Data Source
  connectionStatus?: string;
  selectedSourceType?: string;
  dbName?: string;
  schemaData?: any;
  schemaStatus?: string;
  schemaError?: string;
  onConnect?: (details: any) => Promise<void>;
  onDisconnect?: () => void;
  onSchemaRetry?: () => void;
  // Source type & file selection
  onSourceTypeSelect?: (type: string) => void;
  selectedFile?: File | null;
  onFileSelect?: (file: File) => void;
  onFileUpload?: () => Promise<void>;
  // DB credentials
  dbHost?: string;
  dbPort?: string;
  dbUsername?: string;
  dbPassword?: string;
  setDbHost?: (v: string) => void;
  setDbPort?: (v: string) => void;
  setDbName?: (v: string) => void;
  setDbUsername?: (v: string) => void;
  setDbPassword?: (v: string) => void;
  connectionError?: string;

  // Question & Query
  question?: string;
  submittedQuestion?: string;
  setQuestion?: (q: string) => void;
  onAsk?: (question: string) => void;
  questionSuggestions?: string[];
  suggestionsLoading?: boolean;

  // Goal Agent (Query Execution)
  goalStatus?: string;
  goalResult?: any;
  goalError?: string;
  analysisResult?: any;
  loading?: boolean;
  onAnalyze?: () => Promise<void>;

  // Insight Agent
  insightStatus?: string;
  insightResult?: any;
  insightError?: string;
  onInsightRetry?: () => Promise<void>;

  // History
  historyRefreshKey?: number;
  currentHistorySessionId?: string | null;
  onOpenHistory?: (session: any) => void;
  onDeleteHistory?: (id: string) => void;
}

export const ThemeContext = createContext<ThemeCtx>({
  isDark: false,
  toggleTheme: () => {},
  page: "dashboard",
  setPage: () => {},
});

export const useTheme = () => useContext(ThemeContext);

export default function App({
  user,
  selectedLLM,
  question,
  onAsk,
  onChangeLLM,
  onSignOut,
  // Connection & Data Source
  connectionStatus = "not-connected",
  selectedSourceType = "",
  dbName = "",
  schemaData = null,
  schemaStatus = "idle",
  schemaError = "",
  onConnect,
  onDisconnect,
  onSchemaRetry,
  // Source type & file selection
  onSourceTypeSelect,
  selectedFile,
  onFileSelect,
  onFileUpload,
  // DB credentials
  dbHost = "localhost",
  dbPort = "5432",
  dbUsername = "postgres",
  dbPassword = "",
  setDbHost,
  setDbPort,
  setDbName,
  setDbUsername,
  setDbPassword,
  connectionError = "",
  // Question & Query
  submittedQuestion = "",
  setQuestion,
  questionSuggestions = [],
  suggestionsLoading = false,
  // Goal Agent
  goalStatus = "idle",
  goalResult = null,
  goalError = "",
  analysisResult = null,
  loading = false,
  onAnalyze,
  // Insight Agent
  insightStatus = "idle",
  insightResult = null,
  insightError = "",
  onInsightRetry,
  // History
  historyRefreshKey = 0,
  currentHistorySessionId = null,
  onOpenHistory,
  onDeleteHistory,
}: AppProps) {
  const [isDark, setIsDark] = useState(false);
  const [page, setPage] = useState<Page>("dashboard");

  useEffect(() => {
    document.documentElement.classList.toggle("dark", isDark);
  }, [isDark]);

  const toggleTheme = () => setIsDark((d) => !d);

  const renderPage = () => {
    switch (page) {
      case "dashboard":
        return <Dashboard
          setPage={setPage}
          onAsk={onAsk}
          user={user}
          connectionStatus={connectionStatus}
          dbName={dbName}
          insightResult={insightResult}
          analysisResult={analysisResult}
        />;
      case "analytics":
        return <AIAnalytics
          initialQuery={question}
          onAsk={onAsk}
          analysisResult={analysisResult}
          goalStatus={goalStatus}
          goalResult={goalResult}
          goalError={goalError}
          loading={loading}
        />;
      case "insights":
        return <Insights
          insightResult={insightResult}
          insightStatus={insightStatus}
          insightError={insightError}
        />;
      case "predictive":
        return <Predictive
          insightResult={insightResult}
          goalResult={goalResult}
        />;
      case "prescription":
        return <Prescription
          insightResult={insightResult}
        />;
      case "hypothesis":
        return <Hypothesis
          insightResult={insightResult}
        />;
      case "data":
        return <Data
          connectionStatus={connectionStatus}
          selectedSourceType={selectedSourceType}
          dbName={dbName}
          schemaData={schemaData}
          schemaStatus={schemaStatus}
          schemaError={schemaError}
          onConnect={onConnect}
          onDisconnect={onDisconnect}
          onSchemaRetry={onSchemaRetry}
          onSourceTypeSelect={onSourceTypeSelect}
          selectedFile={selectedFile}
          onFileSelect={onFileSelect}
          onFileUpload={onFileUpload}
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
        />;
      case "documents":
        return <Documents />;
      case "copilot":
        return <Copilot
          analysisResult={analysisResult}
          goalResult={goalResult}
        />;
      case "history":
        return <History
          historyRefreshKey={historyRefreshKey}
          onOpenHistory={onOpenHistory}
          onDeleteHistory={onDeleteHistory}
        />;
      case "settings":
        return <Settings
          selectedLLM={selectedLLM}
          onChangeLLM={onChangeLLM}
          user={user}
        />;
    }
  };

  return (
    <ThemeContext.Provider value={{ isDark, toggleTheme, page, setPage }}>
      <AppShell user={user} selectedLLM={selectedLLM} dbName={dbName} onChangeLLM={onChangeLLM} onSignOut={onSignOut}>
        {renderPage()}
      </AppShell>
    </ThemeContext.Provider>
  );
}
