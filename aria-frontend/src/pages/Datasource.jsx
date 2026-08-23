import DataSourceTypeSelector from "../components/DataSourceTypeSelector";

function DataSource({
  selectedSourceType,
  handleSourceTypeSelect,

  selectedFile,
  handleFileSelect,

  dbHost,
  setDbHost,
  dbPort,
  setDbPort,
  dbName,
  setDbName,
  dbUsername,
  setDbUsername,
  dbPassword,
  setDbPassword,

  connectionStatus,
  connectionError,

  handleDatabaseConnect,
  handleFileUpload,
  handleDataSourceDisconnect,
}) {
  const isConnected = connectionStatus === "connected";
  const isConnecting = connectionStatus === "connecting";
  const isFailed = connectionStatus === "failed";

  const getSourceName = () => {
    if (selectedSourceType === "csv") {
      return "CSV";
    }

    if (selectedSourceType === "pdf") {
      return "PDF";
    }

    if (selectedSourceType === "postgresql") {
      return "PostgreSQL";
    }

    if (selectedSourceType === "mysql") {
      return "MySQL";
    }

    return "Data Source";
  };

  return (
    <>
      {/* =====================================================
          PAGE HEADER
      ===================================================== */}

      <header className="top-header">
        <div>
          <h2>Data Sources</h2>

          <p>Connect or upload the data that ARIA should analyze.</p>
        </div>

        <div className="database-status">
          <span
            className={`status-dot ${
              isConnected
                ? "connected"
                : isConnecting
                  ? "connecting"
                  : isFailed
                    ? "failed"
                    : "disconnected"
            }`}
          ></span>

          {isConnected
            ? `${getSourceName()} Connected`
            : isConnecting
              ? "Processing..."
              : isFailed
                ? "Connection Failed"
                : "No Data Source Connected"}
        </div>
      </header>

      {/* =====================================================
          DATA SOURCE TYPE SELECTOR
      ===================================================== */}

      <DataSourceTypeSelector
        selectedSourceType={selectedSourceType}
        onSelectSourceType={handleSourceTypeSelect}
      />

      {/* =====================================================
          NO SOURCE SELECTED
      ===================================================== */}

      {!selectedSourceType && (
        <section className="source-empty-state">
          <h3>Select a data source to continue</h3>

          <p>Choose CSV, PDF, PostgreSQL, or MySQL above.</p>
        </section>
      )}

      {/* =====================================================
          CSV UPLOAD
      ===================================================== */}

      {selectedSourceType === "csv" && (
        <section className="connection-card">
          <div className="connection-card-header">
            <h3>Upload CSV File</h3>

            <p>Select a structured CSV dataset for ARIA to analyze.</p>
          </div>

          <div className="file-upload-area">
            <div className="file-upload-icon">CSV</div>

            <div className="file-upload-content">
              <h4>{selectedFile ? selectedFile.name : "Choose a CSV file"}</h4>

              <p>Only .csv files are supported for this source type.</p>

              <label className="file-select-button" htmlFor="csv-file">
                Browse CSV
              </label>

              <input
                id="csv-file"
                className="file-input-hidden"
                type="file"
                accept=".csv,text/csv"
                onChange={handleFileSelect}
                disabled={isConnecting || isConnected}
              />
            </div>
          </div>

          {selectedFile && (
            <div className="selected-file-info">
              <div>
                <span>Selected file</span>

                <strong>{selectedFile.name}</strong>
              </div>

              <div>
                <span>Size</span>

                <strong>{(selectedFile.size / 1024).toFixed(1)} KB</strong>
              </div>
            </div>
          )}

          {connectionError && (
            <div className="connection-error">
              <strong>Unable to process file</strong>

              <span>{connectionError}</span>
            </div>
          )}

          {isConnecting && (
            <div className="connection-progress">
              <div className="connection-spinner"></div>

              <div>
                <strong>Preparing CSV dataset</strong>

                <span>ARIA is checking the uploaded file.</span>
              </div>
            </div>
          )}

          {isConnected && (
            <div className="connection-success">
              <strong>CSV uploaded successfully</strong>

              <span>The dataset is ready for Schema Agent processing.</span>
            </div>
          )}

          <div className="connection-actions">
            {!isConnected && (
              <button
                className="connect-button"
                onClick={handleFileUpload}
                disabled={isConnecting}
              >
                {isConnecting ? "Processing..." : "Use This CSV"}
              </button>
            )}

            {isConnected && (
              <button
                className="disconnect-button"
                onClick={handleDataSourceDisconnect}
              >
                Remove Data Source
              </button>
            )}
          </div>
        </section>
      )}

      {/* =====================================================
          PDF UPLOAD
      ===================================================== */}

      {selectedSourceType === "pdf" && (
        <section className="connection-card">
          <div className="connection-card-header">
            <h3>Upload PDF Document</h3>

            <p>Select a PDF document for ARIA to inspect and process.</p>
          </div>

          <div className="file-upload-area">
            <div className="file-upload-icon">PDF</div>

            <div className="file-upload-content">
              <h4>
                {selectedFile ? selectedFile.name : "Choose a PDF document"}
              </h4>

              <p>Only .pdf files are supported for this source type.</p>

              <label className="file-select-button" htmlFor="pdf-file">
                Browse PDF
              </label>

              <input
                id="pdf-file"
                className="file-input-hidden"
                type="file"
                accept=".pdf,application/pdf"
                onChange={handleFileSelect}
                disabled={isConnecting || isConnected}
              />
            </div>
          </div>

          {selectedFile && (
            <div className="selected-file-info">
              <div>
                <span>Selected file</span>

                <strong>{selectedFile.name}</strong>
              </div>

              <div>
                <span>Size</span>

                <strong>{(selectedFile.size / 1024).toFixed(1)} KB</strong>
              </div>
            </div>
          )}

          {connectionError && (
            <div className="connection-error">
              <strong>Unable to process file</strong>

              <span>{connectionError}</span>
            </div>
          )}

          {isConnecting && (
            <div className="connection-progress">
              <div className="connection-spinner"></div>

              <div>
                <strong>Preparing PDF document</strong>

                <span>ARIA is checking the uploaded document.</span>
              </div>
            </div>
          )}

          {isConnected && (
            <div className="connection-success">
              <strong>PDF uploaded successfully</strong>

              <span>The document is ready for backend processing.</span>
            </div>
          )}

          <div className="connection-actions">
            {!isConnected && (
              <button
                className="connect-button"
                onClick={handleFileUpload}
                disabled={isConnecting}
              >
                {isConnecting ? "Processing..." : "Use This PDF"}
              </button>
            )}

            {isConnected && (
              <button
                className="disconnect-button"
                onClick={handleDataSourceDisconnect}
              >
                Remove Data Source
              </button>
            )}
          </div>
        </section>
      )}

      {/* =====================================================
          POSTGRESQL
      ===================================================== */}

      {selectedSourceType === "postgresql" && (
        <section className="connection-card">
          <div className="connection-card-header">
            <h3>PostgreSQL Connection</h3>

            <p>Enter the PostgreSQL database credentials below.</p>
          </div>

          <div className="connection-grid">
            <div className="form-group">
              <label htmlFor="postgres-host">Host</label>

              <input
                id="postgres-host"
                type="text"
                value={dbHost}
                onChange={(event) => setDbHost(event.target.value)}
                placeholder="localhost"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group">
              <label htmlFor="postgres-port">Port</label>

              <input
                id="postgres-port"
                type="text"
                value={dbPort}
                onChange={(event) => setDbPort(event.target.value)}
                placeholder="5432"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group">
              <label htmlFor="postgres-database">Database</label>

              <input
                id="postgres-database"
                type="text"
                value={dbName}
                onChange={(event) => setDbName(event.target.value)}
                placeholder="northwind"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group">
              <label htmlFor="postgres-username">Database Username</label>

              <input
                id="postgres-username"
                type="text"
                value={dbUsername}
                onChange={(event) => setDbUsername(event.target.value)}
                placeholder="postgres"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group full-width">
              <label htmlFor="postgres-password">Database Password</label>

              <input
                id="postgres-password"
                type="password"
                value={dbPassword}
                onChange={(event) => setDbPassword(event.target.value)}
                placeholder="Enter the password for this database user"
                disabled={isConnected || isConnecting}
              />

              <small className="field-helper-text">
                This is the password for the PostgreSQL user above, not your
                ARIA account password. If you do not know it, contact your
                database administrator.
              </small>
            </div>
          </div>

          {connectionError && (
            <div className="connection-error">
              <strong>Unable to connect</strong>

              <span>{connectionError}</span>
            </div>
          )}

          {isConnecting && (
            <div className="connection-progress">
              <div className="connection-spinner"></div>

              <div>
                <strong>Connecting to PostgreSQL</strong>

                <span>ARIA is checking the database connection.</span>
              </div>
            </div>
          )}

          {isConnected && (
            <div className="connection-success">
              <strong>PostgreSQL connected successfully</strong>

              <span>
                Connected to <b>{dbName}</b>. The Schema Agent can now inspect
                this database.
              </span>
            </div>
          )}

          <div className="connection-actions">
            {!isConnected && (
              <button
                className="connect-button"
                onClick={handleDatabaseConnect}
                disabled={isConnecting}
              >
                {isConnecting ? "Connecting..." : "Connect PostgreSQL"}
              </button>
            )}

            {isConnected && (
              <button
                className="disconnect-button"
                onClick={handleDataSourceDisconnect}
              >
                Disconnect Database
              </button>
            )}
          </div>
        </section>
      )}

      {/* =====================================================
          MYSQL
      ===================================================== */}

      {selectedSourceType === "mysql" && (
        <section className="connection-card">
          <div className="connection-card-header">
            <h3>MySQL Connection</h3>

            <p>Enter the MySQL database credentials below.</p>
          </div>

          <div className="connection-grid">
            <div className="form-group">
              <label htmlFor="mysql-host">Host</label>

              <input
                id="mysql-host"
                type="text"
                value={dbHost}
                onChange={(event) => setDbHost(event.target.value)}
                placeholder="localhost"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group">
              <label htmlFor="mysql-port">Port</label>

              <input
                id="mysql-port"
                type="text"
                value={dbPort}
                onChange={(event) => setDbPort(event.target.value)}
                placeholder="3306"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group">
              <label htmlFor="mysql-database">Database</label>

              <input
                id="mysql-database"
                type="text"
                value={dbName}
                onChange={(event) => setDbName(event.target.value)}
                placeholder="business_data"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group">
              <label htmlFor="mysql-username">Database Username</label>

              <input
                id="mysql-username"
                type="text"
                value={dbUsername}
                onChange={(event) => setDbUsername(event.target.value)}
                placeholder="root"
                disabled={isConnected || isConnecting}
              />
            </div>

            <div className="form-group full-width">
              <label htmlFor="mysql-password">Database Password</label>

              <input
                id="mysql-password"
                type="password"
                value={dbPassword}
                onChange={(event) => setDbPassword(event.target.value)}
                placeholder="Enter the password for this database user"
                disabled={isConnected || isConnecting}
              />

              <small className="field-helper-text">
                This is the password for the MySQL user above, not your ARIA
                account password. If you do not know it, contact your database
                administrator.
              </small>
            </div>
          </div>

          {connectionError && (
            <div className="connection-error">
              <strong>Unable to connect</strong>

              <span>{connectionError}</span>
            </div>
          )}

          {isConnecting && (
            <div className="connection-progress">
              <div className="connection-spinner"></div>

              <div>
                <strong>Connecting to MySQL</strong>

                <span>ARIA is checking the database connection.</span>
              </div>
            </div>
          )}

          {isConnected && (
            <div className="connection-success">
              <strong>MySQL connected successfully</strong>

              <span>
                Connected to <b>{dbName}</b>. The Schema Agent can now inspect
                this database.
              </span>
            </div>
          )}

          <div className="connection-actions">
            {!isConnected && (
              <button
                className="connect-button"
                onClick={handleDatabaseConnect}
                disabled={isConnecting}
              >
                {isConnecting ? "Connecting..." : "Connect MySQL"}
              </button>
            )}

            {isConnected && (
              <button
                className="disconnect-button"
                onClick={handleDataSourceDisconnect}
              >
                Disconnect Database
              </button>
            )}
          </div>
        </section>
      )}

      {/* =====================================================
          DEVELOPMENT NOTE
      ===================================================== */}

      {selectedSourceType && (
        <section className="connection-note">
          <strong>Development note</strong>

          <p>
            Data source processing is currently simulated in the frontend. Real
            uploads, secure credential handling, and Schema Agent execution will
            be connected through FastAPI.
          </p>
        </section>
      )}
    </>
  );
}

export default DataSource;
