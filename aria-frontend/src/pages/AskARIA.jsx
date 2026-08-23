function AskARIA({
  question,
  setQuestion,
  loading,
  handleAnalyze,
  connectionStatus,
  dbName,
  selectedSourceType,
  selectedFile,
  questionSuggestions,
  suggestionsLoading,
  handleSuggestionSelect,
}) {
  const isConnected = connectionStatus === "connected";

  const getConnectedSourceName = () => {
    if (!isConnected) {
      return "No data source connected";
    }

    if (selectedSourceType === "csv" || selectedSourceType === "pdf") {
      return selectedFile?.name || "Uploaded file";
    }

    if (selectedSourceType === "postgresql" || selectedSourceType === "mysql") {
      return dbName || "Connected database";
    }

    return "Connected source";
  };

  const getSourceTypeLabel = () => {
    if (selectedSourceType === "postgresql") {
      return "PostgreSQL";
    }

    if (selectedSourceType === "mysql") {
      return "MySQL";
    }

    if (selectedSourceType === "csv") {
      return "CSV";
    }

    if (selectedSourceType === "pdf") {
      return "PDF";
    }

    return "Data Source";
  };

  return (
    <div className="dashboard-page">
      {/* PAGE HEADER */}

      <div className="page-header">
        <div>
          <h1>Ask ARIA</h1>

          <p>Ask a business question about your connected dataset.</p>
        </div>
      </div>

      {/* QUESTION CARD */}

      <section className="section-card">
        <div className="ask-section-heading">
          <div>
            <h3>What would you like to analyze?</h3>

            <p className="ask-helper-text">
              Enter your question in natural language and ARIA will prepare the
              analysis.
            </p>
          </div>

          {isConnected && (
            <div className="ask-source-badge">
              {getSourceTypeLabel()}
              {" · "}
              {getConnectedSourceName()}
            </div>
          )}
        </div>

        <div className="ask-input-wrapper">
          <input
            type="text"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={
              isConnected
                ? "Example: Show me monthly sales trends"
                : "Connect a data source before asking ARIA"
            }
            disabled={loading}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !loading) {
                handleAnalyze();
              }
            }}
          />

          <button
            type="button"
            onClick={handleAnalyze}
            disabled={loading}
            className="primary-button"
          >
            {loading ? "Analyzing..." : "Analyze"}
          </button>
        </div>

        {/* QUESTION SUGGESTIONS */}

        {isConnected && questionSuggestions?.length > 0 && (
          <div className="question-suggestions">
            <div className="suggestion-header">
              <span>Suggested questions</span>

              {suggestionsLoading && <small>Updating...</small>}
            </div>

            <div className="suggestion-list">
              {questionSuggestions.map((suggestion, index) => (
                <button
                  type="button"
                  className="suggestion-item"
                  key={`${suggestion}-${index}`}
                  onClick={() => handleSuggestionSelect(suggestion)}
                >
                  <span className="suggestion-icon">↗</span>

                  <span>{suggestion}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

export default AskARIA;
