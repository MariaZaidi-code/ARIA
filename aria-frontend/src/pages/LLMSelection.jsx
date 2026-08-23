function LLMSelection({ onSelectLLM }) {
  return (
    <div className="llm-page">
      <div className="llm-container">
        <div className="llm-header">
          <h1>Choose Your AI Mode</h1>

          <p>
            Select how you want ARIA to process your requests. You can use a
            faster cloud model or keep processing local for greater privacy.
          </p>
        </div>

        <div className="llm-options">
          {/* ================= CLOUD LLM ================= */}
          <div className="llm-card">
            <div className="llm-card-header">
              <span className="llm-badge">Cloud</span>
              <h2>Cloud LLM</h2>
            </div>

            <p className="llm-description">
              Use Groq-powered cloud models for faster AI responses.
            </p>

            <div className="llm-info">
              <p>
                <strong>Speed:</strong> Faster
              </p>

              <p>
                <strong>Privacy:</strong> Data may be sent to the cloud provider
                for processing.
              </p>

              <p>
                <strong>Best for:</strong> Users who prioritize performance and
                faster responses.
              </p>
            </div>

            <button
              className="llm-select-button"
              onClick={() => onSelectLLM("cloud")}
            >
              Use Cloud LLM
            </button>
          </div>

          {/* ================= LOCAL LLM ================= */}
          <div className="llm-card">
            <div className="llm-card-header">
              <span className="llm-badge">Private</span>
              <h2>Local LLM</h2>
            </div>

            <p className="llm-description">
              Keep AI processing on your local system for greater data privacy.
            </p>

            <div className="llm-info">
              <p>
                <strong>Speed:</strong> Depends on local hardware
              </p>

              <p>
                <strong>Privacy:</strong> Data remains on the user's local
                system.
              </p>

              <p>
                <strong>Best for:</strong> Sensitive or private business data.
              </p>
            </div>

            <button
              className="llm-select-button"
              onClick={() => onSelectLLM("local")}
            >
              Use Local LLM
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LLMSelection;
