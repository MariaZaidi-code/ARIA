import { useState } from "react";
import {
  Database,
  X,
  Server,
  HardDrive,
  TestTube,
  CheckCircle,
  AlertCircle,
  Loader2,
  Wifi,
  Shield,
  ArrowRight,
} from "lucide-react";

const DB_TYPES = [
  { id: "postgresql", name: "PostgreSQL", icon: Database },
  { id: "mysql", name: "MySQL", icon: Database },
  { id: "sqlite", name: "SQLite", icon: HardDrive },
  { id: "sqlserver", name: "SQL Server", icon: Server },
];

export default function DatabaseConnectionPopup({
  onConnect,
  onSkip,
  isConnecting,
  connectionError,
}) {
  const [dbType, setDbType] = useState("postgresql");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState("5432");
  const [dbName, setDbName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [testStatus, setTestStatus] = useState(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleTest = async () => {
    setTestStatus("testing");
    try {
      const res = await fetch("/api/database/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dbType, host, port, dbName, username, password }),
      });
      const data = await res.json();
      setTestStatus(data.success ? "success" : "error");
    } catch {
      setTestStatus("error");
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onConnect({ dbType, host, port, db: dbName, user: username, password });
  };

  const getPortPlaceholder = () => {
    const ports = {
      postgresql: "5432",
      mysql: "3306",
      sqlite: "N/A",
      sqlserver: "1433",
    };
    return ports[dbType] || "5432";
  };

  return (
    <div className="db-popup-overlay">
      <div className="db-popup">
        <button className="db-popup-close" onClick={onSkip} title="Skip for now">
          <X size={20} />
        </button>

        <div className="db-popup-header">
          <div className="db-popup-icon">
            <Database size={28} />
          </div>
          <h2>Connect Your Database</h2>
          <p>
            Link a database to unlock ARIA's full analytics power — or skip to
            explore the dashboard first.
          </p>
        </div>

        <form onSubmit={handleSubmit} className="db-popup-form">
          <div className="db-type-grid">
            {DB_TYPES.map((t) => (
              <button
                key={t.id}
                type="button"
                className={`db-type-card ${dbType === t.id ? "active" : ""}`}
                onClick={() => setDbType(t.id)}
              >
                <t.icon size={18} />
                <span>{t.name}</span>
              </button>
            ))}
          </div>

          {dbType !== "sqlite" && (
            <div className="db-popup-row">
              <div className="db-popup-field flex-2">
                <label>Host</label>
                <input
                  type="text"
                  value={host}
                  onChange={(e) => setHost(e.target.value)}
                  placeholder="localhost"
                />
              </div>
              <div className="db-popup-field flex-1">
                <label>Port</label>
                <input
                  type="text"
                  value={port}
                  onChange={(e) => setPort(e.target.value)}
                  placeholder={getPortPlaceholder()}
                />
              </div>
            </div>
          )}

          <div className="db-popup-field">
            <label>{dbType === "sqlite" ? "File Path" : "Database Name"}</label>
            <input
              type="text"
              value={dbName}
              onChange={(e) => setDbName(e.target.value)}
              placeholder={dbType === "sqlite" ? "/path/to/database.db" : "aria_production"}
              required
            />
          </div>

          {dbType !== "sqlite" && (
            <>
              <button
                type="button"
                className="db-popup-advanced-toggle"
                onClick={() => setShowAdvanced(!showAdvanced)}
              >
                <Shield size={14} />
                {showAdvanced ? "Hide" : "Show"} Authentication
              </button>

              {showAdvanced && (
                <div className="db-popup-auth-fields">
                  <div className="db-popup-row">
                    <div className="db-popup-field flex-1">
                      <label>Username</label>
                      <input
                        type="text"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        placeholder="postgres"
                      />
                    </div>
                    <div className="db-popup-field flex-1">
                      <label>Password</label>
                      <input
                        type="password"
                        value={password}
                        onChange={(e) => setPassword(e.target.value)}
                        placeholder="••••••••"
                      />
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {connectionError && (
            <div className="db-popup-error">
              <AlertCircle size={14} />
              {connectionError}
            </div>
          )}

          <div className="db-popup-actions">
            <button
              type="button"
              className="db-popup-btn-test"
              onClick={handleTest}
              disabled={testStatus === "testing" || !dbName}
            >
              {testStatus === "testing" ? (
                <Loader2 size={15} className="spin" />
              ) : testStatus === "success" ? (
                <CheckCircle size={15} />
              ) : (
                <Wifi size={15} />
              )}
              {testStatus === "testing"
                ? "Testing..."
                : testStatus === "success"
                  ? "Connected"
                  : "Test Connection"}
            </button>

            <button
              type="submit"
              className="db-popup-btn-connect"
              disabled={isConnecting || !dbName}
            >
              {isConnecting ? (
                <Loader2 size={15} className="spin" />
              ) : (
                <>
                  Connect & Continue
                  <ArrowRight size={15} />
                </>
              )}
            </button>
          </div>

          <button type="button" className="db-popup-btn-skip" onClick={onSkip}>
            Skip for now — I'll connect later
          </button>
        </form>
      </div>
    </div>
  );
}
