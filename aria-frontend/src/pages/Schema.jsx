import { useState } from "react";

function Schema({
  connectionStatus,
  selectedSourceType,
  selectedFile,
  dbName,

  schemaStatus,
  schemaData,
  schemaError,

  handleSchemaRetry,
}) {
  const [schemaSearch, setSchemaSearch] = useState("");
  const isConnected = connectionStatus === "connected";

  const isSchemaIdle = schemaStatus === "idle";

  const isSchemaRunning = schemaStatus === "running";

  const isSchemaSuccess = schemaStatus === "success";

  const isSchemaFailed = schemaStatus === "failed";

  // =========================================================
  // SOURCE LABEL
  // =========================================================

  const getSourceLabel = () => {
    if (selectedSourceType === "csv") {
      return "CSV File";
    }

    if (selectedSourceType === "pdf") {
      return "PDF Document";
    }

    if (selectedSourceType === "postgresql") {
      return "PostgreSQL";
    }

    if (selectedSourceType === "mysql") {
      return "MySQL";
    }

    return "Data Source";
  };

  // =========================================================
  // CONNECTED SOURCE NAME
  // =========================================================

  const getConnectedSourceName = () => {
    if (selectedSourceType === "csv" || selectedSourceType === "pdf") {
      return selectedFile?.name || "Uploaded File";
    }

    if (selectedSourceType === "postgresql" || selectedSourceType === "mysql") {
      return dbName || "Connected Database";
    }

    return "Unknown Source";
  };

  // =========================================================
  // SCHEMA STATUS LABEL
  // =========================================================

  const getSchemaStatusLabel = () => {
    if (isSchemaRunning) {
      return "Analyzing...";
    }

    if (isSchemaSuccess) {
      return "Schema Ready";
    }

    if (isSchemaFailed) {
      return "Failed";
    }

    return "Ready to Run";
  };

  // =========================================================
  // SAFE SCHEMA VALUES
  // =========================================================

  const tables = schemaData?.tables || {};

  const relationships = schemaData?.relationship_edges || [];

  const tableCount = Object.keys(tables).length;

  const relationshipCount = relationships.length;

  // =========================================================
  // SEARCH / FILTER
  // =========================================================

  const normalizedSchemaSearch = schemaSearch.trim().toLowerCase();

  const filteredTables = Object.entries(tables).filter(
    ([tableName, tableInfo]) => {
      if (!normalizedSchemaSearch) {
        return true;
      }

      const columns = tableInfo?.columns || [];

      const searchableText = [
        tableName,
        ...columns.map((column) => column?.column || column?.name || ""),
      ]
        .filter(Boolean)
        .map((value) => String(value).toLowerCase())
        .join(" ");

      return searchableText.includes(normalizedSchemaSearch);
    },
  );

  // =========================================================
  // MAIN PAGE
  // =========================================================

  return (
    <>
      {/* =====================================================
          PAGE HEADER
      ===================================================== */}

      <header className="top-header">
        <div>
          <h2>Schema</h2>

          <p>Explore the structure discovered by ARIA's Schema Agent.</p>
        </div>

        <div className="database-status">
          <span
            className={`status-dot ${
              isConnected ? "connected" : "disconnected"
            }`}
          ></span>

          {isConnected ? getConnectedSourceName() : "No Data Source Connected"}
        </div>
      </header>

      {/* =====================================================
          NO DATA SOURCE CONNECTED
      ===================================================== */}

      {!isConnected && (
        <section className="schema-empty-state">
          <div className="schema-empty-icon">DATA</div>

          <h3>No data source connected</h3>

          <p>
            Connect or upload a data source first. ARIA's Schema Agent will then
            inspect its structure.
          </p>
        </section>
      )}

      {/* =====================================================
          CONNECTED DATA SOURCE
      ===================================================== */}

      {isConnected && (
        <>
          {/* =================================================
              SOURCE SUMMARY
          ================================================= */}

          <section className="schema-source-summary">
            <div className="schema-source-card">
              <span>Source Type</span>

              <strong>{getSourceLabel()}</strong>
            </div>

            <div className="schema-source-card">
              <span>Source</span>

              <strong>{getConnectedSourceName()}</strong>
            </div>

            <div className="schema-source-card">
              <span>Connection</span>

              <strong className="schema-ready-text">Connected</strong>
            </div>

            <div className="schema-source-card">
              <span>Schema Agent</span>

              <strong className={isSchemaSuccess ? "schema-ready-text" : ""}>
                {getSchemaStatusLabel()}
              </strong>
            </div>
          </section>

          {/* =================================================
              SCHEMA AGENT IDLE
          ================================================= */}

          {isSchemaIdle && (
            <section className="schema-agent-placeholder">
              <div className="schema-agent-placeholder-icon">AI</div>

              <div>
                <h3>Schema Agent Ready</h3>

                <p>
                  Connect a database or upload a file and ARIA&apos;s Schema
                  Agent will automatically discover its tables, columns,
                  relationships, and data types.
                </p>

                <div className="schema-flow-preview">
                  <span>{getSourceLabel()}</span>

                  <b>→</b>

                  <span>Schema Agent</span>

                  <b>→</b>

                  <span>Schema JSON</span>

                  <b>→</b>

                  <span>Goal Agent</span>
                </div>
              </div>
            </section>
          )}

          {/* =================================================
              SCHEMA AGENT RUNNING
          ================================================= */}

          {isSchemaRunning && (
            <section className="schema-section">
              <div className="connection-progress">
                <div className="connection-spinner"></div>

                <div>
                  <strong>Schema Agent is analyzing your data</strong>

                  <span>
                    ARIA is discovering tables, columns, relationships, data
                    types, and schema information.
                  </span>
                </div>
              </div>

              <div className="schema-flow-preview">
                <span>{getSourceLabel()}</span>

                <b>→</b>

                <span>Schema Agent</span>

                <b>→</b>

                <span>Analyzing...</span>
              </div>
            </section>
          )}

          {/* =================================================
              SCHEMA AGENT FAILED
          ================================================= */}

          {isSchemaFailed && (
            <section className="schema-section">
              <div className="connection-error">
                <strong>ARIA couldn&apos;t analyze this schema</strong>

                <span>
                  Something went wrong while inspecting the data structure. Try
                  the analysis again or reconnect the source.
                </span>

                {schemaError && (
                  <p className="error-detail">Details: {schemaError}</p>
                )}
              </div>

              <div className="connection-actions">
                <button
                  type="button"
                  className="connect-button"
                  onClick={handleSchemaRetry}
                >
                  Retry Schema Analysis
                </button>
              </div>
            </section>
          )}

          {/* =================================================
              SCHEMA AGENT SUCCESS
          ================================================= */}

          {isSchemaSuccess && schemaData && (
            <>
              {/* =============================================
                  SUCCESS NOTICE
              ============================================= */}

              <section className="schema-agent-notice">
                <div>
                  <strong>Schema Agent completed successfully</strong>

                  <p>
                    ARIA discovered the structure of the connected source and
                    stored the schema information for use by the Goal Agent.
                  </p>
                </div>

                <span>Schema Ready</span>
              </section>

              {/* =============================================
                  SCHEMA SUMMARY
              ============================================= */}

              <section className="schema-summary">
                <div className="schema-summary-card">
                  <p>Database</p>

                  <h3>{schemaData.database || getConnectedSourceName()}</h3>
                </div>

                <div className="schema-summary-card">
                  <p>Schema</p>

                  <h3>{schemaData.schema || "Detected"}</h3>
                </div>

                <div className="schema-summary-card">
                  <p>Tables</p>

                  <h3>{tableCount}</h3>
                </div>

                <div className="schema-summary-card">
                  <p>Relationships</p>

                  <h3>{relationshipCount}</h3>
                </div>
              </section>

              {/* =============================================
                  DATABASE TABLES
              ============================================= */}

              <section className="schema-section">
                <div className="schema-section-header">
                  <h3>Database Tables</h3>

                  <p>Tables and columns discovered by ARIA&apos;s Schema Agent.</p>
                </div>

                <div className="schema-search-bar">
                  <input
                    type="text"
                    className="schema-search-input"
                    value={schemaSearch}
                    onChange={(event) => setSchemaSearch(event.target.value)}
                    placeholder="Search tables and columns..."
                  />
                </div>

                {filteredTables.length > 0 ? (
                  <div className="schema-table-grid">
                    {filteredTables.map(([tableName, tableInfo]) => {
                      const columns = tableInfo?.columns || [];

                      const primaryKeys = tableInfo?.primary_key || [];

                      return (
                        <div className="schema-table-card" key={tableName}>
                          <div className="schema-table-title">
                            <h3>{tableName}</h3>

                            <span className="schema-table-count">
                              {columns.length} column{columns.length === 1 ? "" : "s"}
                            </span>
                          </div>

                          <div className="schema-column-header">
                            <span>Column</span>
                            <span>Type</span>
                            <span>Key</span>
                          </div>

                          {columns.map((column, index) => {
                            const columnName =
                              column?.column ||
                              column?.name ||
                              `Column ${index + 1}`;

                            return (
                              <div
                                className="schema-column-row"
                                key={`${tableName}-${columnName}-${index}`}
                              >
                                <span>{columnName}</span>

                                <span>
                                  <span className="schema-dtype-badge">
                                    {column?.data_type ||
                                      column?.type ||
                                      "Unknown"}
                                  </span>
                                </span>

                                <span>
                                  {primaryKeys.includes(columnName) ? (
                                    <span className="schema-key-badge">PK</span>
                                  ) : (
                                    <span className="schema-key-badge muted">-</span>
                                  )}
                                </span>
                              </div>
                            );
                          })}
                        </div>
                      );
                    })}
                  </div>
                ) : normalizedSchemaSearch ? (
                  <div className="schema-empty-state">
                    <div className="empty-state-icon" aria-hidden="true">
                      ⌕
                    </div>

                    <h3>No tables match “{schemaSearch}”</h3>

                    <p>
                      No tables or columns matched your search. Try a different
                      table or column name.
                    </p>
                  </div>
                ) : (
                  <div className="schema-empty-state">
                    <h3>No tables discovered</h3>

                    <p>
                      The Schema Agent completed but did not return any database
                      tables.
                    </p>
                  </div>
                )}
              </section>

              {/* =============================================
                  RELATIONSHIPS
              ============================================= */}

              <section className="schema-section">
                <div className="schema-section-header">
                  <h3>Relationships</h3>

                  <p>Relationships discovered between database tables.</p>
                </div>

                {relationshipCount > 0 ? (
                  <div className="relationship-list">
                    {relationships.map((relationship, index) => (
                      <div
                        className="relationship-card"
                        key={`${relationship.source_table}-${relationship.source_column}-${relationship.target_table}-${relationship.target_column}-${index}`}
                      >
                        <strong>
                          {relationship.source_table}.
                          {relationship.source_column}
                        </strong>

                        <span>→</span>

                        <strong>
                          {relationship.target_table}.
                          {relationship.target_column}
                        </strong>

                        <small>{relationship.type || "Relationship"}</small>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="schema-empty-state">
                    <h3>No relationships discovered</h3>

                    <p>
                      No table relationships were returned by the Schema Agent
                      for this source.
                    </p>
                  </div>
                )}
              </section>
            </>
          )}
        </>
      )}
    </>
  );
}

export default Schema;
