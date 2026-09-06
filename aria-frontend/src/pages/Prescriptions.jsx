import { motion } from "framer-motion";
import { ListChecks, ArrowRight } from "lucide-react";

function PrescriptionsPage({ insightResult, loading, connectionStatus, onStartAnalysis }) {
  const isConnected = connectionStatus === "connected";
  const data = insightResult?.data || insightResult || {};

  const recommendations = Array.isArray(data.recommendations)
    ? data.recommendations
    : Array.isArray(data.prescriptions)
      ? data.prescriptions
      : null;

  const hasPrescriptions = !!recommendations && recommendations.length > 0;
  const empty = !hasPrescriptions && !loading;

  return (
    <div className="dashboard-page">
      {loading && (
        <section className="section-card">
          <div className="insights-placeholder">
            <span className="ask-submit-spinner" aria-hidden="true" />
            <p>Generating recommended actions…</p>
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
              <ListChecks size={32} strokeWidth={1.5} />
            </span>
            <h3>No prescriptions yet</h3>
            <p>
              {isConnected
                ? "Run an analysis to receive actionable recommendations."
                : "Connect a data source to generate recommended actions."}
            </p>
            {isConnected && (
              <button type="button" className="primary-button" onClick={onStartAnalysis}>
                Start an analysis
              </button>
            )}
          </div>
        </motion.section>
      )}

      {hasPrescriptions && (
        <div className="prescriptions-list">
          {recommendations.map((rec, index) => {
            const isString = typeof rec === "string";
            const title = isString ? rec : rec.title || rec.action || `Recommendation ${index + 1}`;
            const description = isString ? "" : rec.description || rec.reason || "";
            const priority = isString ? null : rec.priority || "medium";

            return (
              <motion.section
                className="section-card prescription-card"
                key={index}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.06, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="prescription-head">
                  <span className="prescription-index">{index + 1}</span>
                  <h3>{title}</h3>
                  {priority && (
                    <span className={`priority-badge ${priority}`}>{priority}</span>
                  )}
                </div>

                {description && (
                  <div className="prescription-section">
                    <span className="prescription-label">Finding</span>
                    <p>{description}</p>
                  </div>
                )}

                {!isString && rec.reason && rec.reason !== description && (
                  <div className="prescription-section">
                    <span className="prescription-label">Reason</span>
                    <p>{rec.reason}</p>
                  </div>
                )}

                <div className="prescription-section">
                  <span className="prescription-label">Recommended Action</span>
                  <p className="prescription-action">
                    <ArrowRight size={14} strokeWidth={2} />
                    {title}
                  </p>
                </div>

                {!isString && rec.impact && (
                  <div className="prescription-section">
                    <span className="prescription-label">Expected Impact</span>
                    <p>{rec.impact}</p>
                  </div>
                )}
              </motion.section>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default PrescriptionsPage;
