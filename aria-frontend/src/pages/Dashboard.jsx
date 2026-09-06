import { useEffect, useState, useMemo } from "react";
import {
  BarChart, Bar, ResponsiveContainer, Tooltip, XAxis, YAxis, CartesianGrid,
} from "recharts";
import { Bot, X, Send, ChevronRight, Target, TrendingUp, Lightbulb, AlertTriangle, Activity, Shield } from "lucide-react";
import { getAuthToken } from "../utils/authStorage";

async function apiPost(path, body = {}) {
  const token = getAuthToken();
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
  });
  if (!res.ok) return null;
  return res.json();
}

async function apiGet(path) {
  const token = getAuthToken();
  const res = await fetch(`/api${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) return null;
  return res.json();
}

function fmt(value) {
  if (value == null) return "—";
  const n = Number(value);
  if (isNaN(n)) return String(value);
  if (Math.abs(n) >= 1e6) return `$${(n / 1e6).toFixed(1)}M`;
  if (Math.abs(n) >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
  return n % 1 === 0 ? n.toLocaleString() : n.toFixed(1);
}

const COLORS = ["#4f6cf7", "#22c55e", "#f59e0b", "#8b5cf6", "#06b6d4", "#ef4444"];

function Dashboard({
  submittedQuestion, analysisResult, goalStatus, goalResult, goalError,
  insightResult, insightStatus, connectionStatus, dbName, onQuickAsk, onNavigate, currentUser,
}) {
  const [quickAskValue, setQuickAskValue] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [kpis, setKpis] = useState([]);
  const [loadingKpis, setLoadingKpis] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);
  const [copilotInput, setCopilotInput] = useState("");
  const [copilotMessages, setCopilotMessages] = useState([]);
  const [autocompleteSuggestions, setAutocompleteSuggestions] = useState([]);
  const [showAutocomplete, setShowAutocomplete] = useState(false);

  const isConnected = connectionStatus === "connected";
  const isRunning = goalStatus === "running";
  const hasResult = submittedQuestion && analysisResult;

  // Intelligent autocomplete based on schema
  const schemaSuggestions = useMemo(() => {
    if (!isConnected) return [];
    return [
      "How are sales doing?", "Show revenue by month", "Which products are performing best?",
      "Compare regions", "What happened last quarter?", "Show top customers",
      "Is revenue growing?", "Find anomalies in the data", "What should I focus on?",
      "Show me unusual patterns", "Compare with last year", "What's driving revenue?",
    ];
  }, [isConnected]);

  const handleInputChange = (val) => {
    setQuickAskValue(val);
    if (val.length > 1) {
      const filtered = schemaSuggestions.filter(s =>
        s.toLowerCase().includes(val.toLowerCase())
      ).slice(0, 4);
      setAutocompleteSuggestions(filtered);
      setShowAutocomplete(filtered.length > 0);
    } else {
      setShowAutocomplete(false);
    }
  };

  useEffect(() => {
    if (!isConnected) { setKpis([]); return; }
    let cancelled = false;
    setLoadingKpis(true);
    (async () => {
      try {
        const res = await apiGet("/dashboard/kpis");
        if (!cancelled && res?.ok) setKpis(res.kpis || []);
      } catch {}
      if (!cancelled) setLoadingKpis(false);
    })();
    return () => { cancelled = true; };
  }, [isConnected, dbName]);

  useEffect(() => {
    if (!isConnected) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await apiPost("/suggestions", { limit: 4 });
        if (!cancelled && res?.suggestions) setSuggestions(res.suggestions.slice(0, 4));
      } catch {}
    })();
    return () => { cancelled = true; };
  }, [isConnected, dbName]);

  const submit = () => {
    const t = String(quickAskValue || "").trim();
    if (!t) return;
    onQuickAsk?.(t);
    setQuickAskValue("");
  };

  const askCopilot = async () => {
    const q = String(copilotInput || "").trim();
    if (!q) return;
    setCopilotMessages((m) => [...m, { role: "user", text: q }]);
    setCopilotInput("");
    try {
      const res = await apiPost("/copilot", {
        question: q,
        context: { currentQuery: submittedQuestion, currentResult: analysisResult },
      });
      setCopilotMessages((m) => [...m, { role: "assistant", text: res?.answer || res?.message || "I can help with that." }]);
    } catch {
      setCopilotMessages((m) => [...m, { role: "assistant", text: "Sorry, I couldn't process that." }]);
    }
  };

  /* ── Derive result KPIs ── */
  const resultKpis = (() => {
    if (analysisResult?.kpis?.length > 0) {
      return analysisResult.kpis.slice(0, 4).map((kpi, i) => ({
        label: kpi.label || kpi.name, value: kpi.value ?? "—", color: COLORS[i % COLORS.length],
      }));
    }
    if (goalResult?.kpi_alignment && Object.keys(goalResult.kpi_alignment).length > 0) {
      return Object.entries(goalResult.kpi_alignment).slice(0, 4).map(([key, val], i) => ({
        label: key.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
        value: val, color: COLORS[i % COLORS.length],
      }));
    }
    return [];
  })();

  /* ── Build chart data ── */
  const getChartData = () => {
    if (analysisResult?.charts?.[0]?.data) {
      const c = analysisResult.charts[0];
      return { data: c.data, xKey: c.xKey || "name", yKey: c.yKey || "value", title: c.title };
    }
    const data = analysisResult?.data || analysisResult?.table?.rows || [];
    const columns = analysisResult?.columns || analysisResult?.table?.columns || Object.keys(data[0] || {});
    if (data.length < 2 || columns.length < 2) return null;
    const numCols = columns.filter((c) => data.some((r) => !isNaN(parseFloat(r[c]))));
    const catCols = columns.filter((c) => !numCols.includes(c));
    const x = catCols[0] || columns[0];
    const y = numCols[0] || columns[1];
    return {
      data: data.slice(0, 12).map((r) => ({ name: String(r[x] || "").slice(0, 12), value: parseFloat(r[y]) || 0 })),
      xKey: "name", yKey: "value",
      title: `${y.replace(/_/g, " ")} by ${x.replace(/_/g, " ")}`,
    };
  };
  const chart = getChartData();

  /* ═══════════════════ LOADING ═══════════════════ */
  if (isRunning) {
    return (
      <div className="dash">
        <div className="dash-loading">
          <div className="dash-spinner" />
          <p>Analyzing&hellip;</p>
        </div>
      </div>
    );
  }

  /* ═══════════════════ RESULT ═══════════════════ */
  if (hasResult) {
    const data = analysisResult.data || analysisResult.table?.rows || [];
    const columns = analysisResult.columns || analysisResult.table?.columns || Object.keys(data[0] || {});
    const takeaway = insightResult?.business_story || insightResult?.summary || "";
    const anomalies = goalResult?.anomalies || [];
    const proactiveInsights = goalResult?.proactiveInsights || [];
    const dataQualityWarnings = goalResult?.dataQualityWarnings || [];
    const confidence = goalResult?.confidence || "high";

    return (
      <div className="dash">
        {/* Confidence indicator */}
        {confidence !== "high" && (
          <div className={`dash-confidence dash-confidence--${confidence}`}>
            <Shield size={12} />
            <span>{confidence === "moderate" ? "Moderate confidence — some data quality issues" : "Low confidence — significant data quality concerns"}</span>
          </div>
        )}

        {/* Question header */}
        <div className="dash-result-header">
          <h2>{submittedQuestion}</h2>
        </div>

        {/* KPIs */}
        {resultKpis.length > 0 && (
          <div className="dash-kpis">
            {resultKpis.map((k, i) => (
              <div className="dash-kpi" key={i} style={{ borderLeft: `3px solid ${k.color}` }}>
                <span className="dash-kpi-label">{k.label}</span>
                <span className="dash-kpi-value">{typeof k.value === "number" ? fmt(k.value) : k.value}</span>
              </div>
            ))}
          </div>
        )}

        {/* Chart */}
        {chart && (
          <div className="dash-chart section-card">
            <div className="dash-chart-head">
              <span className="dash-chart-title">{chart.title}</span>
              <span className="dash-chart-badge">{data.length} rows</span>
            </div>
            <ResponsiveContainer width="100%" height={180}>
              <BarChart data={chart.data} margin={{ top: 4, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey={chart.xKey} tick={{ fontSize: 10, fill: "#8c91a3" }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 10, fill: "#8c91a3" }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #e5e7eb", fontSize: 11 }} />
                <Bar dataKey={chart.yKey} fill="#4f6cf7" radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Anomaly detection */}
        {anomalies.length > 0 && (
          <div className="dash-anomaly section-card">
            <div className="dash-anomaly-head">
              <Activity size={14} />
              <span>Anomaly Detected</span>
            </div>
            {anomalies.slice(0, 2).map((a, i) => (
              <p key={i} className="dash-anomaly-text">{a.description}</p>
            ))}
          </div>
        )}

        {/* Proactive insights */}
        {proactiveInsights.length > 0 && (
          <div className="dash-proactive section-card">
            <div className="dash-proactive-head">
              <Lightbulb size={14} />
              <span>ARIA noticed</span>
            </div>
            {proactiveInsights.slice(0, 2).map((p, i) => (
              <p key={i} className="dash-proactive-text">{p.description}</p>
            ))}
          </div>
        )}

        {/* Data quality warnings */}
        {dataQualityWarnings.length > 0 && (
          <div className="dash-quality section-card">
            <div className="dash-quality-head">
              <AlertTriangle size={14} />
              <span>Data Quality</span>
            </div>
            {dataQualityWarnings.slice(0, 2).map((w, i) => (
              <p key={i} className="dash-quality-text">{w.description}</p>
            ))}
          </div>
        )}

        {/* Takeaway */}
        {takeaway && (
          <div className="dash-takeaway section-card">
            <Lightbulb size={14} />
            <p>{takeaway}</p>
          </div>
        )}

        {/* Goal Agent compact */}
        {goalResult && !goalResult.clarificationRequired && (
          <div className="dash-goal section-card">
            <div className="dash-goal-head"><Target size={14} /><span>Goal Analysis</span></div>
            <div className="dash-goal-grid">
              {goalResult.interpretedGoal && (
                <div className="dash-goal-item"><span className="dash-goal-label">Goal</span><span className="dash-goal-val">{goalResult.interpretedGoal}</span></div>
              )}
              {goalResult.generatedSql && (
                <div className="dash-goal-item dash-goal-sql"><span className="dash-goal-label">SQL</span><code>{goalResult.generatedSql}</code></div>
              )}
            </div>
          </div>
        )}

        {/* Follow-up actions */}
        {goalResult?.suggested_questions?.length > 0 && (
          <div className="dash-followup">
            {goalResult.suggested_questions.slice(0, 3).map((q, i) => (
              <button key={i} className="dash-chip" onClick={() => onQuickAsk?.(q)}>{q}</button>
            ))}
          </div>
        )}

        {/* Deep analysis links */}
        <div className="dash-actions">
          <button className="dash-action-link" onClick={() => onNavigate("analytics")}>Explore in Analytics <ChevronRight size={12} /></button>
          <button className="dash-action-link" onClick={() => onNavigate("insights")}>View Insights <ChevronRight size={12} /></button>
          <button className="dash-action-link" onClick={() => onNavigate("predictions")}>Open Prediction <ChevronRight size={12} /></button>
        </div>

        {/* Ask another */}
        <div className="dash-ask-bar section-card">
          <input
            type="text" value={quickAskValue}
            onChange={(e) => handleInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") { setShowAutocomplete(false); submit(); }
              if (e.key === "Escape") setShowAutocomplete(false);
            }}
            onBlur={() => setTimeout(() => setShowAutocomplete(false), 150)}
            placeholder="Ask another question..."
          />
          {showAutocomplete && (
            <div className="dash-autocomplete">
              {autocompleteSuggestions.map((s, i) => (
                <button key={i} className="dash-autocomplete-item" onMouseDown={() => { setQuickAskValue(s); setShowAutocomplete(false); onQuickAsk?.(s); }}>{s}</button>
              ))}
            </div>
          )}
          <button className="dash-ask-btn" onClick={submit}>Ask</button>
        </div>

        {/* Copilot FAB */}
        <button className="dash-copilot-fab" onClick={() => setCopilotOpen(true)} title="Copilot">
          <Bot size={20} />
        </button>

        {/* Copilot side panel */}
        {copilotOpen && (
          <div className="dash-copilot-overlay" onClick={() => setCopilotOpen(false)}>
            <div className="dash-copilot-panel" onClick={(e) => e.stopPropagation()}>
              <div className="dash-copilot-header">
                <span>Copilot</span>
                <button onClick={() => setCopilotOpen(false)}><X size={16} /></button>
              </div>
              <div className="dash-copilot-context">
                {submittedQuestion && <span>Query: {submittedQuestion}</span>}
              </div>
              <div className="dash-copilot-messages">
                {copilotMessages.length === 0 && (
                  <p className="dash-copilot-hint">Ask about your current results, charts, or KPIs.</p>
                )}
                {copilotMessages.map((m, i) => (
                  <div key={i} className={`dash-copilot-msg dash-copilot-msg--${m.role}`}>{m.text}</div>
                ))}
              </div>
              <div className="dash-copilot-input">
                <input
                  type="text" value={copilotInput}
                  onChange={(e) => setCopilotInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && askCopilot()}
                  placeholder="Ask Copilot..."
                />
                <button onClick={askCopilot}><Send size={14} /></button>
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  /* ═══════════════════ IDLE ═══════════════════ */
  return (
    <div className="dash">
      {/* KPIs */}
      {loadingKpis ? (
        <div className="dash-kpis">
          {[1, 2, 3, 4].map((i) => (
            <div className="dash-kpi dash-kpi--skel" key={i}>
              <div className="dash-skel" style={{ width: "50%", height: 10 }} />
              <div className="dash-skel" style={{ width: "35%", height: 22, marginTop: 6 }} />
            </div>
          ))}
        </div>
      ) : kpis.length > 0 ? (
        <div className="dash-kpis">
          {kpis.slice(0, 4).map((kpi, i) => (
            <div className="dash-kpi" key={i} style={{ borderLeft: `3px solid ${kpi.color || COLORS[i % COLORS.length]}` }}>
              <span className="dash-kpi-label">{kpi.label}</span>
              <span className="dash-kpi-value">{fmt(kpi.value, kpi.format)}</span>
            </div>
          ))}
        </div>
      ) : isConnected ? (
        <div className="dash-kpis">
          <div className="dash-kpi" style={{ borderLeft: "3px solid #22c55e" }}>
            <span className="dash-kpi-label">Status</span>
            <span className="dash-kpi-value" style={{ color: "#22c55e" }}>Connected</span>
          </div>
          <div className="dash-kpi" style={{ borderLeft: "3px solid #f59e0b" }}>
            <span className="dash-kpi-label">Source</span>
            <span className="dash-kpi-value">{dbName || "Database"}</span>
          </div>
        </div>
      ) : null}

      {/* Ask ARIA */}
      <div className="dash-ask-bar section-card">
        <input
          type="text" value={quickAskValue}
          onChange={(e) => handleInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { setShowAutocomplete(false); submit(); }
            if (e.key === "Escape") setShowAutocomplete(false);
          }}
          onBlur={() => setTimeout(() => setShowAutocomplete(false), 150)}
          placeholder={isConnected ? "e.g. How did sales perform this quarter?" : "Connect a data source first"}
          disabled={!isConnected}
        />
        {showAutocomplete && (
          <div className="dash-autocomplete">
            {autocompleteSuggestions.map((s, i) => (
              <button key={i} className="dash-autocomplete-item" onMouseDown={() => { setQuickAskValue(s); setShowAutocomplete(false); onQuickAsk?.(s); }}>{s}</button>
            ))}
          </div>
        )}
        <button className="dash-ask-btn" onClick={submit} disabled={!isConnected}>Ask ARIA</button>
      </div>

      {/* Recommended questions */}
      {isConnected && suggestions.length > 0 && (
        <div className="dash-suggestions">
          <span className="dash-suggestions-label">Recommended</span>
          <div className="dash-suggestions-row">
            {suggestions.map((q, i) => (
              <button key={i} className="dash-chip" onClick={() => onQuickAsk?.(q)}>{q}</button>
            ))}
          </div>
        </div>
      )}

      {/* Not connected */}
      {!isConnected && (
        <div className="dash-empty section-card">
          <TrendingUp size={28} strokeWidth={1.5} />
          <h3>No data source connected</h3>
          <p>Connect a database to start analyzing your data.</p>
          <button className="dash-ask-btn" onClick={() => onNavigate("dataSource")}>Connect Database</button>
        </div>
      )}

      {/* Copilot FAB */}
      {isConnected && (
        <button className="dash-copilot-fab" onClick={() => setCopilotOpen(true)} title="Copilot">
          <Bot size={20} />
        </button>
      )}

      {copilotOpen && (
        <div className="dash-copilot-overlay" onClick={() => setCopilotOpen(false)}>
          <div className="dash-copilot-panel" onClick={(e) => e.stopPropagation()}>
            <div className="dash-copilot-header">
              <span>Copilot</span>
              <button onClick={() => setCopilotOpen(false)}><X size={16} /></button>
            </div>
            <div className="dash-copilot-messages">
              <p className="dash-copilot-hint">Ask about your data, KPIs, or results.</p>
            </div>
            <div className="dash-copilot-input">
              <input
                type="text" value={copilotInput}
                onChange={(e) => setCopilotInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && askCopilot()}
                placeholder="Ask Copilot..."
              />
              <button onClick={askCopilot}><Send size={14} /></button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default Dashboard;
