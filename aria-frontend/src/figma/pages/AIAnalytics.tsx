import { useState, useRef, useEffect } from "react";
import { Search, X, Clock, Copy, ChevronDown, ChevronUp, Sparkles, ArrowRight, CheckCircle, Loader2, Code2, Table2 } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area } from "recharts";
import { useTheme } from "../App";

type AnalysisState = "idle" | "processing" | "done";

interface AIAnalyticsProps {
  initialQuery?: string;
  onAsk?: (question: string) => void;
  analysisResult?: any;
  goalStatus?: string;
  goalResult?: any;
  goalError?: string;
  loading?: boolean;
}

const recentQueries = [
  "Which product category generated the highest revenue in Q3?",
  "Compare revenue between North America and Europe",
  "What is the average order value by customer segment?",
  "Show me top 10 products by margin",
];

export default function AIAnalytics({
  initialQuery = "",
  onAsk,
  analysisResult = null,
  goalStatus = "idle",
  goalResult = null,
  goalError = "",
  loading = false,
}: AIAnalyticsProps) {
  const { isDark } = useTheme();
  const [query, setQuery] = useState(initialQuery);
  const [sqlExpanded, setSqlExpanded] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showTable, setShowTable] = useState(true);
  const inputRef = useRef<HTMLInputElement>(null);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  // Derive state from props
  const state: AnalysisState =
    loading || goalStatus === "running" ? "processing" :
    analysisResult && goalStatus === "success" ? "done" :
    "idle";

  const runAnalysis = (q?: string) => {
    const text = q || query;
    if (!text.trim()) return;
    setQuery(text);
    onAsk?.(text);
  };

  const copySQL = () => {
    const sql = goalResult?.sql_used || goalResult?.generatedSql || "";
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Extract real data from results
  const sqlUsed = goalResult?.sql_used || goalResult?.generatedSql || "";
  const tableData = analysisResult?.data || [];
  const chartData = tableData.slice(0, 10);
  const followUps = goalResult?.suggested_questions || [];

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">AI Analytics</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Ask questions. Explore your data. Get answers.</p>
      </div>

      {/* Query Composer */}
      <div className="space-y-3">
        <div className="flex items-center gap-3 bg-card border border-border rounded-xl px-4 py-3.5 focus-within:border-primary/50 focus-within:shadow-[0_0_0_3px_var(--primary-light)] transition-all duration-200" style={{ boxShadow: 'var(--shadow-sm)' }}>
          <Sparkles size={16} className="text-primary flex-shrink-0" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && runAnalysis()}
            placeholder="Which product category generated the highest revenue in Q3?"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
          />
          {query && (
            <button onClick={() => { setQuery(""); }} className="text-muted-foreground hover:text-foreground transition-colors">
              <X size={15} />
            </button>
          )}
          <button
            onClick={() => runAnalysis()}
            className="premium-btn btn-glow flex-shrink-0 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all"
            style={{ background: 'var(--gradient-primary)' }}
          >
            Analyze
          </button>
        </div>

        {/* Recent queries */}
        {state === "idle" && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5"><Clock size={11} /> Recent</p>
            <div className="flex flex-wrap gap-2">
              {recentQueries.map((q) => (
                <button
                  key={q}
                  onClick={() => runAnalysis(q)}
                  className="text-xs px-3 py-1.5 bg-secondary hover:bg-secondary/70 border border-border rounded-full text-muted-foreground hover:text-foreground transition-colors truncate max-w-xs"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Processing */}
      {state === "processing" && (
        <div className="bg-card border border-border rounded-xl p-6 flex flex-col items-center gap-5">
          <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
            <Loader2 size={20} className="text-primary animate-spin" />
          </div>
          <p className="text-sm text-muted-foreground">Analyzing your question...</p>
        </div>
      )}

      {/* Error */}
      {goalError && (
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <p className="text-sm text-negative font-medium">{goalError}</p>
        </div>
      )}

      {/* Results */}
      {state === "done" && tableData.length > 0 && (
        <div className="space-y-4">
          {/* Answer */}
          {goalResult?.message && (
            <div className="premium-card bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                  <Sparkles size={12} className="text-primary" />
                </div>
                <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Answer</p>
              </div>
              <p className="text-[14px] font-medium text-foreground leading-relaxed">
                {goalResult.message}
              </p>
              <div className="flex flex-wrap gap-4 pt-1 text-[11px] text-muted-foreground">
                <span>Rows: <span className="text-foreground font-medium">{tableData.length}</span></span>
                <span>Confidence: <span className="text-positive font-medium">{goalResult.confidence || "High"}</span></span>
              </div>
            </div>
          )}

          {/* Visualization */}
          {chartData.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">Visualization</p>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} barSize={36}>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                  <XAxis dataKey={Object.keys(chartData[0] || {})[0]} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                  <Tooltip
                    contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                    labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                  />
                  <Bar dataKey={Object.keys(chartData[0] || {})[1] || "value"} fill="var(--primary)" radius={[5, 5, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Table */}
          <div className="bg-card border border-border rounded-xl overflow-hidden">
            <button
              onClick={() => setShowTable((t) => !t)}
              className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-secondary/40 transition-colors"
            >
              <div className="flex items-center gap-2">
                <Table2 size={14} className="text-muted-foreground" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Supporting Data</p>
              </div>
              {showTable ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
            </button>
            {showTable && tableData.length > 0 && (
              <div className="border-t border-border overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      {Object.keys(tableData[0]).map((h) => (
                        <th key={h} className="text-left text-xs font-medium text-muted-foreground px-5 py-3">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.slice(0, 50).map((row, i) => (
                      <tr key={i} className={`${i < tableData.slice(0, 50).length - 1 ? "border-b border-border" : ""} hover:bg-secondary/30 transition-colors`}>
                        {Object.values(row).map((val: any, j) => (
                          <td key={j} className="px-5 py-3 text-foreground">{String(val)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* SQL */}
          {sqlUsed && (
            <div className="bg-card border border-border rounded-xl overflow-hidden">
              <button
                onClick={() => setSqlExpanded((e) => !e)}
                className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-secondary/40 transition-colors"
              >
                <div className="flex items-center gap-2">
                  <Code2 size={14} className="text-muted-foreground" />
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Generated SQL</p>
                </div>
                {sqlExpanded ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
              </button>
              {sqlExpanded && (
                <div className="border-t border-border">
                  <div className="flex items-center justify-between px-4 py-2 bg-muted/60">
                    <span className="text-xs text-muted-foreground font-mono">SQL Query</span>
                    <div className="flex gap-2">
                      <button onClick={copySQL} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                        <Copy size={12} /> {copied ? "Copied!" : "Copy"}
                      </button>
                    </div>
                  </div>
                  <pre className="font-mono text-xs text-foreground px-5 py-4 overflow-x-auto leading-relaxed bg-muted/30">
                    <code>{sqlUsed}</code>
                  </pre>
                </div>
              )}
            </div>
          )}

          {/* Follow-ups */}
          {followUps.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Continue your analysis</p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 stagger-children">
                {followUps.map((q, i) => (
                  <button
                    key={i}
                    onClick={() => { setQuery(q); runAnalysis(q); }}
                    className="premium-card flex items-center justify-between bg-card border border-border rounded-xl px-4 py-3 hover:border-primary/40 text-left group"
                  >
                    <p className="text-sm text-foreground group-hover:text-primary transition-colors">{q}</p>
                    <ArrowRight size={13} className="text-muted-foreground group-hover:text-primary transition-colors ml-2 flex-shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
