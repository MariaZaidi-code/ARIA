import { useEffect, useState } from "react";
import { Cpu, Sun, Moon, Database, ShieldCheck, History, ChevronRight } from "lucide-react";
import AriaLogo from "../components/AriaLogo";

function SettingsPage({
  selectedLLM,
  handleChangeLLM,
  theme,
  onToggleTheme,
  connectionStatus,
  selectedSourceType,
  dbName,
  selectedFile,
  currentUser,
  onNavigate,
}) {
  const isConnected = connectionStatus === "connected";

  const [history, setHistory] = useState([]);
  const [historyLoading, setHistoryLoading] = useState(true);

  useEffect(() => {
    let live = true;

    async function load() {
      const token = localStorage.getItem("aria_auth_token");
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      try {
        const response = await fetch("/api/history", { headers });
        if (response.ok) {
          const data = await response.json();
          const items = (data.items || []).filter(
            (s) => !currentUser?.email || s.userEmail === currentUser.email,
          );
          if (live) setHistory(items);
        }
      } catch {
        // noop
      } finally {
        if (live) setHistoryLoading(false);
      }
    }

    load();

    return () => {
      live = false;
    };
  }, [currentUser?.email]);

  const recentHistory = [...history]
    .sort(
      (a, b) =>
        new Date(b.createdAt || 0).getTime() - new Date(a.createdAt || 0).getTime(),
    )
    .slice(0, 4);

  const getSourceSummary = () => {
    if (!isConnected) return "No data source connected";
    if (selectedSourceType === "csv" || selectedSourceType === "pdf")
      return selectedFile?.name || "Uploaded file";
    if (selectedSourceType === "postgresql" || selectedSourceType === "mysql")
      return dbName || "Connected database";
    return "Connected source";
  };

  const formatDate = (value) => {
    if (!value) return "";
    return new Date(value).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="settings-page">
      <div className="settings-grid">
        {/* AI ENGINE */}
        <section className="settings-card">
          <div className="settings-card-head">
            <span className="settings-card-icon" aria-hidden="true">
              <Cpu size={18} strokeWidth={2} />
            </span>
            <div>
              <h3>AI Engine</h3>
              <p>Where ARIA runs its agents.</p>
            </div>
          </div>

          <div className="settings-option-list">
            <button
              type="button"
              className={`settings-option ${selectedLLM === "cloud" ? "active" : ""}`}
              onClick={() => handleChangeLLM()}
            >
              <div className="settings-option-copy">
                <strong>Cloud LLM</strong>
                <span>Fast, hosted intelligence</span>
              </div>
              <span className="settings-option-check" aria-hidden="true" />
            </button>

            <button
              type="button"
              className={`settings-option ${selectedLLM === "local" ? "active" : ""}`}
              onClick={() => handleChangeLLM()}
            >
              <div className="settings-option-copy">
                <strong>Local LLM</strong>
                <span>Private, on-device processing</span>
              </div>
              <span className="settings-option-check" aria-hidden="true" />
            </button>
          </div>
        </section>

        {/* APPEARANCE */}
        <section className="settings-card">
          <div className="settings-card-head">
            <span className="settings-card-icon" aria-hidden="true">
              {theme === "dark" ? (
                <Sun size={18} strokeWidth={2} />
              ) : (
                <Moon size={18} strokeWidth={2} />
              )}
            </span>
            <div>
              <h3>Appearance</h3>
              <p>Control the look and feel of ARIA.</p>
            </div>
          </div>

          <button type="button" className="settings-row" onClick={onToggleTheme}>
            <span>Theme</span>
            <span className="settings-row-value">
              {theme === "dark" ? "Dark" : "Light"}
              <span className="settings-toggle" aria-hidden="true" />
            </span>
          </button>
        </section>

        {/* DATA SOURCE */}
        <section className="settings-card">
          <div className="settings-card-head">
            <span className="settings-card-icon" aria-hidden="true">
              <Database size={18} strokeWidth={2} />
            </span>
            <div>
              <h3>Data Source</h3>
              <p>Your currently connected source.</p>
            </div>
          </div>

          <div className="settings-row">
            <span className="settings-row-value settings-source">
              <span className={`settings-source-dot ${isConnected ? "ok" : ""}`} />
              {getSourceSummary()}
            </span>
          </div>

          <button
            type="button"
            className="settings-link"
            onClick={() => onNavigate && onNavigate("dataSource")}
          >
            Manage data source
            <ChevronRight size={15} strokeWidth={2} />
          </button>
        </section>

        {/* HISTORY */}
        <section className="settings-card settings-card--history">
          <div className="settings-card-head">
            <span className="settings-card-icon" aria-hidden="true">
              <History size={18} strokeWidth={2} />
            </span>
            <div>
              <h3>History</h3>
              <p>Your recent analysis sessions.</p>
            </div>

            <button
              type="button"
              className="settings-link"
              onClick={() => onNavigate && onNavigate("history")}
            >
              View all
              <ChevronRight size={15} strokeWidth={2} />
            </button>
          </div>

          {historyLoading ? (
            <div className="settings-skeleton" aria-hidden="true" />
          ) : recentHistory.length > 0 ? (
            <div className="settings-history-list">
              {recentHistory.map((session) => (
                <button
                  type="button"
                  key={session.id}
                  className="settings-history-item"
                  onClick={() => onNavigate && onNavigate("history")}
                >
                  <span className="settings-history-q">{session.question}</span>
                  <span className="settings-history-date">
                    {formatDate(session.createdAt)}
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <div className="settings-empty">
              No analyses yet. Ask ARIA a question to get started.
            </div>
          )}

          <div className="settings-count">
            {recentHistory.length} of {history.length} analyses shown
          </div>
        </section>

        {/* SECURITY */}
        <section className="settings-card">
          <div className="settings-card-head">
            <span className="settings-card-icon" aria-hidden="true">
              <ShieldCheck size={18} strokeWidth={2} />
            </span>
            <div>
              <h3>Security</h3>
              <p>Your data stays under your control.</p>
            </div>
          </div>

          <div className="settings-brand-row">
            <AriaLogo size={20} />
            <span>ARIA Business Analytics</span>
          </div>
        </section>
      </div>
    </div>
  );
}

export default SettingsPage;