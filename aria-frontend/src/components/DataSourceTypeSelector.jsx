function DataSourceTypeSelector({ selectedSourceType, onSelectSourceType }) {
  const sourceTypes = [
    {
      id: "csv",
      title: "CSV File",
      shortLabel: "CSV",
      description: "Upload structured tabular data stored in a CSV file.",
      category: "File Upload",
    },

    {
      id: "pdf",
      title: "PDF Document",
      shortLabel: "PDF",
      description: "Upload a PDF document for ARIA to inspect and process.",
      category: "File Upload",
    },

    {
      id: "postgresql",
      title: "PostgreSQL",
      shortLabel: "PostgreSQL",
      description: "Connect ARIA directly to an existing PostgreSQL database.",
      category: "Database",
    },

    {
      id: "mysql",
      title: "MySQL",
      shortLabel: "MySQL",
      description: "Connect ARIA directly to an existing MySQL database.",
      category: "Database",
    },
  ];

  return (
    <section className="source-type-section">
      <div className="source-type-header">
        <div>
          <h3>Choose a Data Source</h3>

          <p>Select the type of data you want ARIA to analyze.</p>
        </div>
      </div>

      <div className="source-type-grid">
        {sourceTypes.map((source) => {
          const isSelected = selectedSourceType === source.id;

          return (
            <button
              type="button"
              key={source.id}
              className={`source-type-card ${isSelected ? "selected" : ""}`}
              onClick={() => onSelectSourceType(source.id)}
            >
              <div className="source-type-card-top">
                <span className="source-type-icon">{source.shortLabel}</span>

                <span className="source-type-category">{source.category}</span>
              </div>

              <h4>{source.title}</h4>

              <p>{source.description}</p>

              <span className="source-select-text">
                {isSelected ? "Selected" : "Select source"}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

export default DataSourceTypeSelector;
