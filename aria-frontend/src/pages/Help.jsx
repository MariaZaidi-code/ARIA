function Help() {
  return (
    <div className="help-page">
      <div className="page-header">
        <h1>Help & Support</h1>
        <p>Get help using ARIA and understand the main analytics workflow.</p>
      </div>

      <div className="help-grid">
        <div className="help-card">
          <h3>Getting Started</h3>
          <p>
            Connect a data source, wait for the Schema Agent, then ask ARIA a
            business question.
          </p>
        </div>

        <div className="help-card">
          <h3>Ask ARIA</h3>
          <p>
            Use natural-language questions to generate KPIs, charts, insights,
            anomalies, and hypotheses.
          </p>
        </div>

        <div className="help-card">
          <h3>History & Reports</h3>
          <p>
            Previous analyses are saved in History. Important analyses can also
            be saved as reports.
          </p>
        </div>

        <div className="help-card">
          <h3>AI Mode</h3>
          <p>
            Use LLM Settings to switch between Local LLM and Cloud LLM modes.
          </p>
        </div>
      </div>
    </div>
  );
}

export default Help;
