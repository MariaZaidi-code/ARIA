function DataSourceSelection({ onSelectSource, onClose, connectionStatus }) {
  const isConnected = connectionStatus === "connected";

  const options = [
    {
      id: "postgresql",
      title: "PostgreSQL",
      description: "Connect a PostgreSQL database.",
      tag: "DB",
    },
    {
      id: "mysql",
      title: "MySQL",
      description: "Connect a MySQL database.",
      tag: "DB",
    },
    {
      id: "csv",
      title: "CSV",
      description: "Upload/import a CSV file.",
      tag: "FILE",
    },
    {
      id: "pdf",
      title: "PDF",
      description: "Upload a PDF/document for document intelligence.",
      tag: "DOC",
    },
  ];

  return (
    <div className="datasource-select">
      <div className="datasource-select-card">
        <div className="datasource-select-head">
          <div>
            <h2>How would you like to provide your data?</h2>

            <p>
              Choose the data source you want to work with. You can connect a
              database or upload a file.
            </p>
          </div>

          <button
            type="button"
            className="datasource-close"
            onClick={onClose}
            aria-label="Close data source selection"
            title="Close"
          >
            ×
          </button>
        </div>

        <div className="datasource-select-grid">
          {options.map((option) => (
            <button
              type="button"
              key={option.id}
              className="datasource-select-option"
              onClick={() => onSelectSource(option.id)}
            >
              <span className="datasource-option-tag">{option.tag}</span>

              <strong>{option.title}</strong>

              <span>{option.description}</span>

              <span className="datasource-option-cta">
                {isConnected ? "Change source" : "Get started"} →
              </span>
            </button>
          ))}
        </div>

        <button
          type="button"
          className="datasource-select-skip"
          onClick={onClose}
        >
          Not now — go to my workspace
        </button>
      </div>
    </div>
  );
}

export default DataSourceSelection;
