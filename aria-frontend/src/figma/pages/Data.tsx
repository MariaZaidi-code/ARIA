import { useState, useRef } from "react";
import {
  Database, FileSpreadsheet, FileText, Server, Plug, CheckCircle,
  AlertTriangle, RefreshCw, Table, XCircle, Upload, Loader2,
  Eye, ChevronRight, Zap,
} from "lucide-react";

type SourceType = "postgresql" | "mysql" | "csv" | "pdf" | "";
type Tab = "sources" | "schema" | "preview" | "quality";

const SOURCES = [
  { id: "postgresql" as SourceType, label: "PostgreSQL", icon: Server, color: "#336791", bgColor: "rgba(51,103,145,0.08)", description: "Connect to a PostgreSQL database for full analytics.", category: "Database" },
  { id: "mysql" as SourceType, label: "MySQL", icon: Database, color: "#00758F", bgColor: "rgba(0,117,143,0.08)", description: "Connect to a MySQL database for full analytics.", category: "Database" },
  { id: "csv" as SourceType, label: "CSV File", icon: FileSpreadsheet, color: "#217346", bgColor: "rgba(33,115,70,0.08)", description: "Upload a structured CSV dataset for analysis.", category: "File Upload" },
  { id: "pdf" as SourceType, label: "PDF Document", icon: FileText, color: "#B30B00", bgColor: "rgba(179,11,0,0.08)", description: "Upload a PDF document for AI-powered extraction.", category: "File Upload" },
];

const tabs: { id: Tab; label: string }[] = [
  { id: "sources", label: "Connected Sources" },
  { id: "schema", label: "Schema" },
  { id: "preview", label: "Data Preview" },
  { id: "quality", label: "Data Quality" },
];

// ── Module-level Field component (stable identity — no remount on keystroke) ──
function Field({ label, id, type, value, onChange, placeholder, disabled, children }: {
  label: string; id: string; type?: string; value: string;
  onChange: (v: string) => void; placeholder?: string;
  disabled?: boolean; children?: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">{label}</label>
      <div className="relative">
        <input
          id={id}
          type={type === "password-show" ? "text" : type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          disabled={disabled}
          className={`w-full bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground
            placeholder:text-muted-foreground outline-none focus:border-primary
            focus:shadow-[0_0_0_3px_var(--primary-light)] transition-all duration-150
            ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
        />
        {children}
      </div>
    </div>
  );
}

// ── Module-level SourceCard component ──
function SourceCard({ s, selected, onClick }: {
  s: typeof SOURCES[0]; selected: boolean; onClick: () => void;
}) {
  const Icon = s.icon;
  return (
    <button
      onClick={onClick}
      className={`relative premium-card rounded-xl p-4 text-left transition-all duration-200 group cursor-pointer
        ${selected ? "border-primary/50 shadow-glow" : "border-border"}`}
      style={{ background: selected ? s.bgColor : "var(--card)" }}
    >
      <div className="absolute top-0 left-0 right-0 h-[3px] rounded-t-xl transition-opacity duration-200"
        style={{ background: `linear-gradient(90deg, ${s.color}, ${s.color}88)`, opacity: selected ? 1 : 0 }} />
      <div className="flex items-start gap-3">
        <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 transition-all duration-200"
          style={{ background: `${s.color}18` }}>
          <Icon size={16} style={{ color: s.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-0.5">
            <p className="text-sm font-semibold text-foreground">{s.label}</p>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
              style={{ background: `${s.color}15`, color: s.color }}>{s.category}</span>
          </div>
          <p className="text-[11px] text-muted-foreground leading-relaxed">{s.description}</p>
        </div>
        {selected && <CheckCircle size={14} className="flex-shrink-0 text-primary mt-0.5" />}
      </div>
      <div className="absolute inset-0 rounded-xl opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none"
        style={{ boxShadow: `0 0 0 1px ${s.color}30, 0 8px 24px -4px ${s.color}25` }} />
    </button>
  );
}

interface Props {
  connectionStatus?: string;
  selectedSourceType?: string;
  dbName?: string;
  schemaData?: any;
  schemaStatus?: string;
  schemaError?: string;
  onConnect?: (details: any) => Promise<void>;
  onDisconnect?: () => void;
  onSchemaRetry?: () => void;
  onSourceTypeSelect?: (type: string) => void;
  selectedFile?: File | null;
  onFileSelect?: (file: File) => void;
  onFileUpload?: () => Promise<void>;
  connectionError?: string;
}

export default function Data({
  connectionStatus = "not-connected",
  selectedSourceType = "",
  dbName = "",
  schemaData,
  schemaStatus = "idle",
  schemaError = "",
  onConnect,
  onDisconnect,
  onSchemaRetry,
  onSourceTypeSelect,
  selectedFile,
  onFileSelect,
  onFileUpload,
  connectionError = "",
}: Props) {
  const [activeTab, setActiveTab] = useState<Tab>("sources");
  const [localSourceType, setLocalSourceType] = useState<SourceType>("" as SourceType);
  const [localFile, setLocalFile] = useState<File | null>(null);
  const [localError, setLocalError] = useState("");
  const [localConnecting, setLocalConnecting] = useState(false);
  const [lHost, setLHost] = useState("localhost");
  const [lPort, setLPort] = useState("5432");
  const [lDbName, setLDbName] = useState("");
  const [lUser, setLUser] = useState("postgres");
  const [lPass, setLPass] = useState("");
  const [selectedTable, setSelectedTable] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const sourceType = selectedSourceType || localSourceType;
  const file = selectedFile !== undefined ? selectedFile : localFile;
  const error = connectionError || localError;
  const connecting = connectionStatus === "connecting" || localConnecting;
  const isConnected = connectionStatus === "connected";
  const tables = schemaData?.tables || {};
  const tableNames = Object.keys(tables);
  const currentTable = tables[selectedTable];
  const columns = currentTable?.columns || {};
  const tableCount = tableNames.length;

  const sourceMeta = SOURCES.find((s) => s.id === sourceType);
  const SourceIcon = sourceMeta?.icon || Plug;

  const handleSourceSelect = (id: SourceType) => {
    if (connecting) return;
    setLocalSourceType(id);
    setLocalFile(null);
    setLocalError("");
    onSourceTypeSelect?.(id);
    if (id === "mysql") { setLPort("3306"); setLUser("root"); setLDbName(""); }
    if (id === "postgresql") { setLPort("5432"); setLUser("postgres"); setLDbName(""); }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const ext = f.name.split(".").pop()?.toLowerCase() ?? "";
    const allowed = sourceType === "pdf" ? "pdf" : "csv";
    if (ext !== allowed) { setLocalError(`Only .${allowed} files are supported.`); return; }
    setLocalError("");
    setLocalFile(f);
    onFileSelect?.(f);
  };

  const handleConnect = async () => {
    setLocalError("");
    if (!sourceType) return;
    setLocalConnecting(true);
    try {
      if (sourceType === "csv" || sourceType === "pdf") {
        if (!file) { setLocalError("Please select a file first."); return; }
        await onFileUpload?.();
      } else {
        if (!lHost.trim()) { setLocalError("Host is required."); return; }
        if (!lDbName.trim()) { setLocalError("Database name is required."); return; }
        if (!lUser.trim()) { setLocalError("Username is required."); return; }
        if (!lPass.trim()) { setLocalError("Password is required."); return; }
        if (!/^\d+$/.test(lPort)) { setLocalError("Port must be numbers only."); return; }
        await onConnect?.({ host: lHost, port: lPort, db: lDbName, user: lUser, password: lPass, sourceType });
      }
    } catch (err: any) {
      setLocalError(err?.message || "Connection failed.");
    } finally {
      setLocalConnecting(false);
    }
  };

  const handleDisconnect = () => {
    setLocalSourceType("" as SourceType);
    setLocalFile(null);
    setLocalError("");
    setLHost("localhost"); setLPort("5432"); setLDbName(""); setLUser("postgres"); setLPass("");
    onDisconnect?.();
  };

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-5">
      {/* Page header */}
      <div className="animate-fade-in">
        <h2 className="text-base font-bold text-foreground tracking-tight">Data Sources</h2>
        <p className="text-xs text-muted-foreground mt-0.5">
          Connect a database, upload a CSV, or import a PDF — ARIA analyzes everything.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-secondary rounded-lg p-0.5 w-fit">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setActiveTab(t.id)}
            className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors
              ${activeTab === t.id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── SOURCES TAB ── */}
      {activeTab === "sources" && (
        <div className="space-y-5">

          {/* Connected status banner */}
          {isConnected && (
            <div className="premium-card bg-positive/5 border border-positive/20 rounded-xl p-4 animate-fade-in">
              <div className="flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-lg bg-positive/10 flex items-center justify-center">
                    <SourceIcon size={16} className="text-positive" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-semibold text-foreground">{dbName || sourceMeta?.label}</p>
                      <span className="flex items-center gap-1 text-[11px] text-positive font-medium">
                        <span className="w-1.5 h-1.5 rounded-full bg-positive" /> Connected
                      </span>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {sourceMeta?.category} · {tableCount} tables · Ready for analysis
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={onSchemaRetry}
                    className="flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground px-3 py-1.5 rounded-lg hover:bg-secondary transition-all">
                    <RefreshCw size={11} /> Refresh schema
                  </button>
                  <button onClick={handleDisconnect}
                    className="flex items-center gap-1.5 text-[11px] text-negative hover:text-negative/80 px-3 py-1.5 rounded-lg hover:bg-negative/5 transition-all">
                    <XCircle size={11} /> Disconnect
                  </button>
                </div>
              </div>
              <div className="mt-3 bg-secondary/60 rounded-full h-1">
                <div className="h-1 rounded-full bg-positive transition-all duration-500"
                  style={{ width: schemaStatus === "success" ? "100%" : schemaStatus === "running" ? "65%" : "25%" }} />
              </div>
              <div className="flex items-center justify-between mt-1.5">
                <span className="text-[10px] text-muted-foreground">
                  {schemaStatus === "success" ? "Schema ready" : schemaStatus === "running" ? "Loading schema..." : "Schema pending"}
                </span>
                {schemaError && (
                  <span className="text-[10px] text-negative flex items-center gap-1">
                    <AlertTriangle size={10} /> {schemaError}
                  </span>
                )}
              </div>
            </div>
          )}

          {/* Source type selector — always shown when not connected */}
          {!isConnected && (
            <div>
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
                <Zap size={11} /> Choose a data source
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {SOURCES.map((s) => (
                  <SourceCard
                    key={s.id}
                    s={s}
                    selected={sourceType === s.id}
                    onClick={() => handleSourceSelect(s.id)}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Connection form — shown when sourceType is set AND not connected */}
          {sourceType && !isConnected && (
            <div className="animate-slide-in-bottom">
              <div className="divider-gradient mb-5" />

              {/* PostgreSQL / MySQL form */}
              {(sourceType === "postgresql" || sourceType === "mysql") && (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 mb-1">
                    <SourceIcon size={14} style={{ color: sourceMeta?.color }} />
                    <p className="text-sm font-semibold text-foreground">{sourceMeta?.label} Connection</p>
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <Field label="Host" id="db-host" value={lHost} onChange={setLHost}
                      placeholder="localhost" disabled={connecting} />
                    <Field label="Port" id="db-port" value={lPort} onChange={setLPort}
                      placeholder={sourceType === "mysql" ? "3306" : "5432"} disabled={connecting} />
                    <Field label="Database Name" id="db-name" value={lDbName} onChange={setLDbName}
                      placeholder="northwind" disabled={connecting} />
                    <Field label="Username" id="db-user" value={lUser} onChange={setLUser}
                      placeholder={sourceType === "mysql" ? "root" : "postgres"} disabled={connecting} />
                  </div>
                  <Field label="Password" id="db-pass" type="password-show" value={lPass}
                    onChange={setLPass} placeholder="Enter password" disabled={connecting}>
                    <button type="button"
                      onClick={() => setShowPassword((s) => !s)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground text-[10px]">
                      {showPassword ? "Hide" : "Show"}
                    </button>
                  </Field>

                  {error && (
                    <div className="flex items-center gap-2 bg-negative/8 border border-negative/20 rounded-lg px-3 py-2.5">
                      <AlertTriangle size={13} className="text-negative flex-shrink-0" />
                      <p className="text-xs text-negative">{error}</p>
                    </div>
                  )}

                  <button onClick={handleConnect} disabled={connecting}
                    className="premium-btn btn-glow w-full sm:w-auto px-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-50"
                    style={{ background: "var(--gradient-primary)" }}>
                    {connecting ? (
                      <><Loader2 size={13} className="animate-spin" /> Connecting...</>
                    ) : (
                      <><Plug size={13} /> Connect {sourceMeta?.label}</>
                    )}
                  </button>
                </div>
              )}

              {/* CSV upload form */}
              {sourceType === "csv" && (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 mb-1">
                    <FileSpreadsheet size={14} style={{ color: sourceMeta?.color }} />
                    <p className="text-sm font-semibold text-foreground">Upload CSV File</p>
                  </div>
                  <div onClick={() => fileInputRef.current?.click()}
                    className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200
                      ${file ? "border-primary/40 bg-primary/4" : "border-border hover:border-primary/40 hover:bg-primary/2"}`}>
                    <input ref={fileInputRef} type="file" accept=".csv,text/csv"
                      onChange={handleFileChange} disabled={connecting} className="hidden" />
                    <FileSpreadsheet size={28}
                      className={`mx-auto mb-2 transition-colors ${file ? "text-primary" : "text-muted-foreground"}`} />
                    {file ? (
                      <>
                        <p className="text-sm font-medium text-foreground">{file.name}</p>
                        <p className="text-[11px] text-muted-foreground mt-1">{(file.size / 1024).toFixed(1)} KB · Click to change</p>
                      </>
                    ) : (
                      <>
                        <p className="text-sm font-medium text-foreground">Drop a CSV here or click to browse</p>
                        <p className="text-[11px] text-muted-foreground mt-1">.csv files only · Up to 100MB</p>
                      </>
                    )}
                  </div>
                  {error && (
                    <div className="flex items-center gap-2 bg-negative/8 border border-negative/20 rounded-lg px-3 py-2.5">
                      <AlertTriangle size={13} className="text-negative flex-shrink-0" />
                      <p className="text-xs text-negative">{error}</p>
                    </div>
                  )}
                  <button onClick={handleConnect} disabled={!file || connecting}
                    className="premium-btn btn-glow w-full sm:w-auto px-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-50"
                    style={{ background: "var(--gradient-primary)" }}>
                    {connecting ? (
                      <><Loader2 size={13} className="animate-spin" /> Processing...</>
                    ) : (
                      <><Upload size={13} /> Upload & Analyze CSV</>
                    )}
                  </button>
                </div>
              )}

              {/* PDF upload form */}
              {sourceType === "pdf" && (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 mb-1">
                    <FileText size={14} style={{ color: sourceMeta?.color }} />
                    <p className="text-sm font-semibold text-foreground">Upload PDF Document</p>
                  </div>
                  <div onClick={() => fileInputRef.current?.click()}
                    className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200
                      ${file ? "border-primary/40 bg-primary/4" : "border-border hover:border-primary/40 hover:bg-primary/2"}`}>
                    <input ref={fileInputRef} type="file" accept=".pdf,application/pdf"
                      onChange={handleFileChange} disabled={connecting} className="hidden" />
                    <FileText size={28}
                      className={`mx-auto mb-2 transition-colors ${file ? "text-primary" : "text-muted-foreground"}`} />
                    {file ? (
                      <>
                        <p className="text-sm font-medium text-foreground">{file.name}</p>
                        <p className="text-[11px] text-muted-foreground mt-1">{(file.size / 1024).toFixed(1)} KB · Click to change</p>
                      </>
                    ) : (
                      <>
                        <p className="text-sm font-medium text-foreground">Drop a PDF here or click to browse</p>
                        <p className="text-[11px] text-muted-foreground mt-1">.pdf files only · Up to 50MB</p>
                      </>
                    )}
                  </div>
                  {error && (
                    <div className="flex items-center gap-2 bg-negative/8 border border-negative/20 rounded-lg px-3 py-2.5">
                      <AlertTriangle size={13} className="text-negative flex-shrink-0" />
                      <p className="text-xs text-negative">{error}</p>
                    </div>
                  )}
                  <button onClick={handleConnect} disabled={!file || connecting}
                    className="premium-btn btn-glow w-full sm:w-auto px-6 py-2.5 rounded-xl text-sm font-semibold text-white flex items-center justify-center gap-2 disabled:opacity-50"
                    style={{ background: "var(--gradient-primary)" }}>
                    {connecting ? (
                      <><Loader2 size={13} className="animate-spin" /> Processing...</>
                    ) : (
                      <><Upload size={13} /> Upload & Analyze PDF</>
                    )}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ── SCHEMA TAB ── */}
      {activeTab === "schema" && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <div className="px-3 py-2.5 border-b border-border">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Tables ({tableNames.length})</p>
            </div>
            <div className="max-h-80 overflow-y-auto">
              {tableNames.map((name) => (
                <button key={name} onClick={() => setSelectedTable(name)}
                  className={`w-full flex items-center justify-between px-3 py-2 hover:bg-secondary/40 transition-colors border-b border-border/50 last:border-0
                    ${selectedTable === name ? "bg-secondary/60" : ""}`}>
                  <div className="flex items-center gap-2 text-left">
                    <Table size={12} className="text-muted-foreground flex-shrink-0" />
                    <div>
                      <p className="text-xs font-medium text-foreground font-mono">{name}</p>
                      <p className="text-[10px] text-muted-foreground">{tables[name]?.row_count ?? "?"} rows</p>
                    </div>
                  </div>
                  <ChevronRight size={11} className="text-muted-foreground" />
                </button>
              ))}
              {tableNames.length === 0 && (
                <div className="p-6 text-center">
                  <Table size={20} className="mx-auto text-muted-foreground mb-2" />
                  <p className="text-xs text-muted-foreground">
                    {isConnected ? "Schema loading..." : "Connect a data source to view schema."}
                  </p>
                </div>
              )}
            </div>
          </div>

          <div className="md:col-span-2 bg-card border border-border rounded-xl overflow-hidden">
            <div className="px-4 py-2.5 border-b border-border flex items-center justify-between">
              <p className="text-xs font-semibold text-foreground font-mono">{selectedTable || "Select a table"}</p>
              {selectedTable && (
                <span className="text-[11px] text-muted-foreground">{Object.keys(columns).length} columns</span>
              )}
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left text-[11px] font-medium text-muted-foreground px-4 py-2.5">Column</th>
                    <th className="text-left text-[11px] font-medium text-muted-foreground px-4 py-2.5">Type</th>
                    <th className="text-left text-[11px] font-medium text-muted-foreground px-4 py-2.5">Nullable</th>
                    <th className="text-left text-[11px] font-medium text-muted-foreground px-4 py-2.5">Sample</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(columns).map(([colName, colInfo]: [string, any], i, arr) => (
                    <tr key={colName}
                      className={`${i < arr.length - 1 ? "border-b border-border" : ""} hover:bg-secondary/30 transition-colors`}>
                      <td className="px-4 py-2 font-mono text-xs text-foreground font-medium">{colName}</td>
                      <td className="px-4 py-2 font-mono text-xs text-primary">{colInfo?.dtype || "text"}</td>
                      <td className="px-4 py-2 text-xs text-muted-foreground">{colInfo?.nullable !== false ? "YES" : "NO"}</td>
                      <td className="px-4 py-2 font-mono text-[10px] text-muted-foreground truncate max-w-[140px]">
                        {colInfo?.sample_values?.[0] ?? "—"}
                      </td>
                    </tr>
                  ))}
                  {Object.keys(columns).length === 0 && (
                    <tr>
                      <td colSpan={4} className="px-4 py-8 text-center text-xs text-muted-foreground">
                        {isConnected ? "Select a table to view its columns." : "Connect a data source first."}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* ── PREVIEW TAB ── */}
      {activeTab === "preview" && (
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <Eye size={24} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">Data Preview</p>
          <p className="text-xs text-muted-foreground mt-1">
            {isConnected ? "Run an analysis to see live data here." : "Connect a data source and run an analysis to preview results."}
          </p>
        </div>
      )}

      {/* ── QUALITY TAB ── */}
      {activeTab === "quality" && (
        <div className="bg-card border border-border rounded-xl p-8 text-center">
          <CheckCircle size={24} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">Data Quality</p>
          <p className="text-xs text-muted-foreground mt-1">
            {isConnected ? "Schema analysis is in progress. Check back after running your first query." : "Connect a data source to run data quality checks."}
          </p>
        </div>
      )}
    </div>
  );
}
