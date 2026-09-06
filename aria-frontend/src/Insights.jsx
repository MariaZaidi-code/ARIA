import { motion } from "framer-motion";
import {
  Sparkles,
  TrendingUp,
  AlertTriangle,
  Lightbulb,
  ListChecks,
  BarChart3,
  ArrowRight,
} from "lucide-react";
import AriaLogo from "../components/AriaLogo";

const renderItem = (item, fallbackIndex) => {
  if (typeof item === "string") return item;
  return item?.title || item?.description || `Insight ${fallbackIndex + 1}`;
};

const renderDesc = (item) => {
  if (typeof item === "string") return null;
  return item?.description || item?.finding || null;
};

function InsightSection({ icon, tone, title, items, render, children }) {
  if (!items || items.length === 0) return null;
  return (
    <motion.section
      className="section-card"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="insights-card-head">
        <span className={`insights-card-icon ${tone || ""}`} aria-hidden="true">
          {icon}
        </span>
        <h3>{title}</h3>
      </div>
      {children}
    </motion.section>
  );
}

function InsightsPage({ insightResult, loading, connectionStatus, onStartAnalysis }) {
  const isConnected = connectionStatus === "connected";
  const hasInsights = !!insightResult;

  const data = insightResult?.data || insightResult || {};

  const keyInsights = Array.isArray(data.keyInsights) && data.keyInsights.length
    ? data.keyInsights
    : Array.isArray(data.insights) && data.insights.length
      ? data.insights
      : null;

  const trends = Array.isArray(data.trends) && data.trends.length ? data.trends : null;
  const anomalies = Array.isArray(data.anomalies) && data.anomalies.length ? data.anomalies : null;
  const hypotheses = Array.isArray(data.hypotheses) && data.hypotheses.length ? data.hypotheses : null;
  const recommendations = Array.isArray(data.recommendations) && data.recommendations.length ? data.recommendations : null;

  const empty = !hasInsights && !loading;

  return (
    <div className="dashboard-page">
      <div className="page-header">
        <div>
          <span className="dashboard-eyebrow">Intelligence</span>
          <h1>Insights</h1>
          <p>Key findings, trends, and anomalies surfaced by the Agents.</p>
        </div>
      </div>

      {loading && (
        <section className="section-card">
          <div className="insights-placeholder">
            <span className="ask-submit-spinner" aria-hidden="true" />
            <p>Agents are analyzing your data…</p>
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
              <Sparkles size={32} strokeWidth={1.5} />
            </span>
            <h3>No insights yet</h3>
            <p>
              {isConnected
                ? "Run an analysis to surface key insights from your data."
                : "Connect a data source and run an analysis to get started."}
            </p>
            {isConnected && (
              <button type="button" className="primary-button" onClick={onStartAnalysis}>
                Start an analysis
              </button>
            )}
          </div>
        </motion.section>
      )}

      {hasInsights && (
        <div className="insights-grid">
          {keyInsights && (
            <InsightSection icon={<Sparkles size={18} strokeWidth={2} />} title="Key Insights" items={keyInsights}>
              <ul className="insights-list">
                {keyInsights.map((insight, index) => (
                  <li key={index} className="insight-item insight-item-structured">
                    <span className="insight-item-dot" />
                    <div className="insight-item-body">
                      <strong>{renderItem(insight, index)}</strong>
                      {renderDesc(insight) && <span>{renderDesc(insight)}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            </InsightSection>
          )}

          {trends && (
            <InsightSection icon={<TrendingUp size={18} strokeWidth={2} />} title="Trends" items={trends}>
              <ul className="insights-list">
                {trends.map((trend, index) => (
                  <li key={index} className="insight-item insight-item-structured">
                    <span className={`insight-item-dot trend ${typeof trend === "object" ? trend.direction === "down" ? "down" : trend.direction === "up" ? "up" : "" : ""}`} />
                    <div className="insight-item-body">
                      <strong>{renderItem(trend, index)}</strong>
                      {renderDesc(trend) && <span>{renderDesc(trend)}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            </InsightSection>
          )}

          {anomalies && (
            <InsightSection icon={<AlertTriangle size={18} strokeWidth={2} />} title="Anomalies" items={anomalies} tone="warn">
              <ul className="insights-list">
                {anomalies.map((anomaly, index) => (
                  <li key={index} className="insight-item insight-item-structured">
                    <span className="insight-item-dot warn" />
                    <div className="insight-item-body">
                      <strong>{renderItem(anomaly, index)}</strong>
                      {renderDesc(anomaly) && <span>{renderDesc(anomaly)}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            </InsightSection>
          )}

          {recommendations && (
            <InsightSection icon={<ListChecks size={18} strokeWidth={2} />} title="Recommendations" items={recommendations}>
              <ul className="insights-list">
                {recommendations.map((rec, index) => {
                  const isString = typeof rec === "string";
                  return (
                    <li key={index} className="insight-item insight-item-structured">
                      <span className="insight-item-check" aria-hidden="true">
                        <ArrowRight size={14} strokeWidth={2} />
                      </span>
                      <div className="insight-item-body">
                        <strong>{renderItem(rec, index)}</strong>
                        {!isString && rec.description && <span>{rec.description}</span>}
                      </div>
                    </li>
                  );
                })}
              </ul>
            </InsightSection>
          )}

          {hypotheses && (
            <InsightSection icon={<Lightbulb size={18} strokeWidth={2} />} title="Hypotheses" items={hypotheses}>
              <ul className="insights-list">
                {hypotheses.map((hyp, index) => (
                  <li key={index} className="insight-item insight-item-structured">
                    <span className="insight-item-dot hyp" />
                    <div className="insight-item-body">
                      <strong>{renderItem(hyp, index)}</strong>
                      {renderDesc(hyp) && <span>{renderDesc(hyp)}</span>}
                    </div>
                  </li>
                ))}
              </ul>
            </InsightSection>
          )}

          {data.businessStory && (
            <motion.section
              className="section-card full-bleed"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05, duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            >
              <div className="insights-card-head">
                <span className="insights-card-icon" aria-hidden="true">
                  <BarChart3 size={18} strokeWidth={2} />
                </span>
                <h3>The Story</h3>
                <div className="insights-brand">
                  <AriaLogo size={16} />
                </div>
              </div>
              <p className="insights-story">{data.businessStory}</p>
            </motion.section>
          )}
        </div>
      )}
    </div>
  );
}

export default InsightsPage;
