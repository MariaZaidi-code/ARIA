import { motion } from "framer-motion";
import { TrendingUp, LineChart } from "lucide-react";

function PredictionsPage({ insightResult, loading, connectionStatus, onStartAnalysis }) {
  const isConnected = connectionStatus === "connected";
  const data = insightResult?.data || insightResult || {};

  const predictions = Array.isArray(data.predictions) ? data.predictions : null;

  const hasPredictions = !!predictions && predictions.length > 0;
  const empty = !hasPredictions && !loading;

  const confidenceLabel = (value) => {
    if (typeof value === "string") return value;
    if (typeof value === "number" && !Number.isNaN(value)) {
      return `${Math.round((value < 1 ? value : value / 100) * 100)}%`;
    }
    return null;
  };

  return (
    <div className="dashboard-page">
      {loading && (
        <section className="section-card">
          <div className="insights-placeholder">
            <span className="ask-submit-spinner" aria-hidden="true" />
            <p>Forecasting future outcomes…</p>
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
              <TrendingUp size={32} strokeWidth={1.5} />
            </span>
            <h3>No predictions yet</h3>
            <p>
              {isConnected
                ? "Run an analysis to generate forward-looking predictions from your historical data."
                : "Connect a data source to generate predictions."}
            </p>
            {isConnected && (
              <button type="button" className="primary-button" onClick={onStartAnalysis}>
                Start an analysis
              </button>
            )}
          </div>
        </motion.section>
      )}

      {hasPredictions && (
        <div className="predictions-grid">
          <motion.section
            className="section-card prediction-hero"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
          >
            <div className="insights-card-head">
              <span className="insights-card-icon" aria-hidden="true">
                <LineChart size={18} strokeWidth={2} />
              </span>
              <h3>Forecast</h3>
            </div>

            <div className="prediction-list">
              {predictions.map((pred, index) => {
                const isString = typeof pred === "string";
                const title = isString ? pred : pred.title || `Forecast ${index + 1}`;
                const description = isString ? "" : pred.description || "";

                return (
                  <div className="prediction-item" key={index}>
                    <div className="prediction-item-head">
                      <strong>{title}</strong>
                      {!isString && pred.confidence && (
                        <span className="confidence-badge">
                          {confidenceLabel(pred.confidence)} confidence
                        </span>
                      )}
                    </div>
                    {description && <p>{description}</p>}
                  </div>
                );
              })}
            </div>
          </motion.section>
        </div>
      )}
    </div>
  );
}

export default PredictionsPage;
