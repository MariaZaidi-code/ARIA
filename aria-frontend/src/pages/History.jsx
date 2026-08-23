import { useState } from "react";

import { getHistorySessions } from "../utils/historyStorage";

function History({
  currentUser,
  handleOpenHistorySession,
  handleSaveReport,
  handleDeleteHistorySession,
}) {
  const [searchTerm, setSearchTerm] = useState("");

  const [sourceFilter, setSourceFilter] = useState("all");

  const [dateFilter, setDateFilter] = useState("all");

  // =========================================================
  // DAY 9 - LOAD HISTORY
  // =========================================================

  const allHistorySessions = getHistorySessions().filter(
    (session) => !currentUser?.email || session.userEmail === currentUser.email,
  );

  const normalizedSearch = searchTerm.trim().toLowerCase();

  const matchesDateFilter = (session) => {
    if (dateFilter === "all") {
      return true;
    }

    if (!session.createdAt) {
      return false;
    }

    const sessionDate = new Date(session.createdAt);

    const now = new Date();

    if (dateFilter === "today") {
      return (
        sessionDate.getFullYear() === now.getFullYear() &&
        sessionDate.getMonth() === now.getMonth() &&
        sessionDate.getDate() === now.getDate()
      );
    }

    const cutoffDate = new Date();

    if (dateFilter === "7days") {
      cutoffDate.setDate(now.getDate() - 7);

      return sessionDate >= cutoffDate;
    }

    if (dateFilter === "30days") {
      cutoffDate.setDate(now.getDate() - 30);

      return sessionDate >= cutoffDate;
    }

    return true;
  };

  const historySessions = allHistorySessions.filter((session) => {
    const matchesSource =
      sourceFilter === "all" || session.source?.type === sourceFilter;

    const matchesDate = matchesDateFilter(session);

    const searchableText = [
      session.question,
      session.source?.name,
      session.source?.type,
      session.goal?.goalType,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    const matchesSearch =
      normalizedSearch === "" || searchableText.includes(normalizedSearch);

    return matchesSource && matchesDate && matchesSearch;
  });

  // =========================================================
  // FORMAT DATE
  // =========================================================

  const formatHistoryDate = (dateValue) => {
    if (!dateValue) {
      return "Unknown date";
    }

    return new Date(dateValue).toLocaleString();
  };

  return (
    <div className="history-page">
      {/* ===============================================
          PAGE HEADER
      ================================================ */}

      <div className="page-header">
        <div>
          <h1>Analysis History</h1>

          <p>Review and reopen your previous ARIA analysis sessions.</p>
        </div>

        <div className="history-count-badge">
          {historySessions.length}{" "}
          {historySessions.length === 1 ? "analysis" : "analyses"}
        </div>
      </div>
      <div className="history-toolbar">
        <input
          type="text"
          className="history-search-input"
          value={searchTerm}
          onChange={(event) => setSearchTerm(event.target.value)}
          placeholder="Search by question, dataset, source type, or analysis type..."
        />
        <select
          className="history-filter-select"
          value={sourceFilter}
          onChange={(event) => setSourceFilter(event.target.value)}
        >
          <option value="all">All Sources</option>

          <option value="postgresql">PostgreSQL</option>

          <option value="mysql">MySQL</option>

          <option value="csv">CSV</option>

          <option value="pdf">PDF</option>
        </select>

        <select
          className="history-filter-select"
          value={dateFilter}
          onChange={(event) => setDateFilter(event.target.value)}
        >
          <option value="all">All Dates</option>

          <option value="today">Today</option>

          <option value="7days">Last 7 Days</option>

          <option value="30days">Last 30 Days</option>
        </select>
      </div>
      {/* ===============================================
          EMPTY STATE
      ================================================ */}

      {historySessions.length === 0 && (
        <section className="section-card">
          <div>
            <h3>No analysis history yet</h3>

            <p>
              Completed ARIA analyses will automatically appear here so you can
              revisit previous questions, dashboards, and insights.
            </p>
          </div>
        </section>
      )}

      {/* ===============================================
          HISTORY LIST
      ================================================ */}

      {historySessions.length > 0 && (
        <div className="history-list">
          {historySessions.map((session) => {
            const chartCount = session.analytics?.charts?.length || 0;

            const insightCount = session.insights?.keyInsights?.length || 0;

            return (
              <article className="history-card" key={session.id}>
                <div className="history-card-top">
                  <div>
                    <span className="history-card-label">
                      Business Question
                    </span>

                    <h3>{session.question}</h3>
                  </div>

                  <span className="history-status-badge">Completed</span>
                </div>

                <div className="history-card-meta">
                  <div>
                    <span>Data Source</span>

                    <strong>{session.source?.name || "Unknown source"}</strong>
                  </div>

                  <div>
                    <span>Source Type</span>

                    <strong>{session.source?.type || "Unknown"}</strong>
                  </div>

                  <div>
                    <span>AI Mode</span>

                    <strong>
                      {session.llmMode === "local" ? "Local LLM" : "Cloud LLM"}
                    </strong>
                  </div>

                  <div>
                    <span>Visualizations</span>

                    <strong>{chartCount}</strong>
                  </div>

                  <div>
                    <span>Key Insights</span>

                    <strong>{insightCount}</strong>
                  </div>
                </div>

                <div className="history-card-footer">
                  <div className="history-card-footer-info">
                    <span>{formatHistoryDate(session.createdAt)}</span>

                    <span>{session.goal?.goalType || "General analysis"}</span>
                  </div>

                  <button
                    type="button"
                    className="history-open-button"
                    onClick={() => handleOpenHistorySession(session)}
                  >
                    Open Analysis
                  </button>

                  <button
                    type="button"
                    className="history-save-button"
                    onClick={() => handleSaveReport(session.id)}
                    disabled={session.savedReport === true}
                  >
                    {session.savedReport ? "Saved Report" : "Save Report"}
                  </button>

                  <button
                    type="button"
                    className="history-delete-button"
                    onClick={() => {
                      const confirmed = window.confirm(
                        "Delete this analysis permanently from History?",
                      );

                      if (confirmed) {
                        handleDeleteHistorySession(session.id);
                      }
                    }}
                  >
                    Delete
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default History;
