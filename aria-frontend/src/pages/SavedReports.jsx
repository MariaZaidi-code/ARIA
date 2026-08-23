import { getHistorySessions } from "../utils/historyStorage";

function SavedReports({
  currentUser,
  handleOpenHistorySession,
  handleRemoveSavedReport,
}) {
  // =========================================================
  // DAY 9 - LOAD SAVED REPORTS
  // =========================================================

  const savedReports = getHistorySessions().filter(
    (session) =>
      session.savedReport === true &&
      (!currentUser?.email || session.userEmail === currentUser.email),
  );

  // =========================================================
  // FORMAT DATE
  // =========================================================

  const formatSavedDate = (dateValue) => {
    if (!dateValue) {
      return "Unknown date";
    }

    return new Date(dateValue).toLocaleString();
  };

  return (
    <div className="saved-reports-page">
      {/* ===============================================
          PAGE HEADER
      ================================================ */}

      <div className="page-header">
        <div>
          <h1>Saved Reports</h1>

          <p>Access the ARIA analyses you saved for future review.</p>
        </div>

        <div className="history-count-badge">
          {savedReports.length}{" "}
          {savedReports.length === 1 ? "report" : "reports"}
        </div>
      </div>

      {/* ===============================================
          EMPTY STATE
      ================================================ */}

      {savedReports.length === 0 && (
        <section className="section-card">
          <h3>No saved reports yet</h3>

          <p>Save an analysis from History and it will appear here.</p>
        </section>
      )}

      {/* ===============================================
          SAVED REPORT LIST
      ================================================ */}

      {savedReports.length > 0 && (
        <div className="history-list">
          {savedReports.map((session) => {
            const chartCount = session.analytics?.charts?.length || 0;

            const insightCount = session.insights?.keyInsights?.length || 0;

            return (
              <article className="history-card" key={session.id}>
                <div className="history-card-top">
                  <div>
                    <span className="history-card-label">Saved Analysis</span>

                    <h3>{session.question}</h3>
                  </div>

                  <span className="history-status-badge">Saved</span>
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
                    <span>Saved {formatSavedDate(session.savedAt)}</span>

                    <span>{session.goal?.goalType || "General analysis"}</span>
                  </div>

                  <button
                    type="button"
                    className="history-open-button"
                    onClick={() => handleOpenHistorySession(session)}
                  >
                    Open Report
                  </button>
                  <button
                    type="button"
                    className="saved-report-remove-button"
                    onClick={() => handleRemoveSavedReport(session.id)}
                  >
                    Remove from Saved
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

export default SavedReports;
