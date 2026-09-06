import { motion } from "framer-motion";
import { Lightbulb, Scale } from "lucide-react";

function HypothesisPage({ insightResult, loading, connectionStatus, onStartAnalysis }) {
  const isConnected = connectionStatus === "connected";
  const data = insightResult?.data || insightResult || {};

  const hypotheses = Array.isArray(data.hypotheses)
    ? data.hypotheses
    : null;

  const hasHypotheses = !!hypotheses && hypotheses.length > 0;
  const empty = !hasHypotheses && !loading;

  const confidenceLabel = (value) => {
    if (typeof value === "number" && !Number.isNaN(value)) {
      return `${Math.round((value < 1 ? value : value / 100) * 100)}%`;
    }
    if (typeof value === "string") return value;
    return null;
  };

  return (
    <div className="dashboard-page">
      {loading && (
        <section className="section-card">
          <div className="insights-placeholder">
            <span className="ask-submit-spinner" aria-hidden="true" />
            <p>Evaluating hypotheses…</p>
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
              <Lightbulb size={32} strokeWidth={1.5} />
            </span>
            <h3>No hypotheses yet</h3>
            <p>
              {isConnected
                ? "Run an analysis to surface and evaluate possible explanations."
                : "Connect a data source to investigate business questions."}
            </p>
            {isConnected && (
              <button type="button" className="primary-button" onClick={onStartAnalysis}>
                Start an analysis
              </button>
            )}
          </div>
        </motion.section>
      )}

      {hasHypotheses && (
        <div className="hypothesis-list">
          {hypotheses.map((hyp, index) => {
            const isString = typeof hyp === "string";
            const title = isString ? hyp : hyp.title || `Hypothesis ${index + 1}`;
            const description = isString ? "" : hyp.description || hyp.basis || "";
            const confidence = isString ? null : confidenceLabel(hyp.confidence);
            const rank = isString ? null : hyp.rank || index + 1;
            const evidence = !isString && Array.isArray(hyp.evidence) ? hyp.evidence : [];

            return (
              <motion.section
                className="section-card hypothesis-card"
                key={index}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: index * 0.06, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
              >
                <div className="hypothesis-head">
                  <span className="hypothesis-rank">{rank || index + 1}</span>
                  <h3>{title}</h3>
                  {confidence && (
                    <span className="confidence-badge">{confidence} confidence</span>
                  )}
                </div>

                {(description || evidence.length > 0) && (
                  <div className="prescription-section">
                    <span className="prescription-label">Available Evidence</span>
                    {description && <p>{description}</p>}
                    {evidence.length > 0 && (
                      <ul className="hypothesis-evidence">
                        {evidence.map((item, i) => (
                          <li key={i}>{item}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {!isString && (hyp.assumptions || hyp.limitations) && (
                  <div className="prescription-section">
                    <span className="prescription-label">Assumptions &amp; Limitations</span>
                    <p>
                      {hyp.assumptions ? `${hyp.assumptions} ` : ""}
                      {hyp.limitations ? ` ${hyp.limitations}` : ""}
                    </p>
                  </div>
                )}

                {!isString && hyp.result && (
                  <div className="prescription-section">
                    <span className="prescription-label">Result</span>
                    <p>{hyp.result}</p>
                  </div>
                )}

                <div className="hypothesis-note">
                  <Scale size={14} strokeWidth={2} />
                  <span>Hypotheses are evaluated against available data and are not presented as confirmed facts.</span>
                </div>
              </motion.section>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default HypothesisPage;
