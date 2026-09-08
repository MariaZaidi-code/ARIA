import { useState, useRef, useEffect } from "react";
import { Search, X, Clock, Copy, ChevronDown, ChevronUp, Sparkles, ArrowRight, CheckCircle, Loader2, Code2, Table2, AlertCircle, Database, GitBranch } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, LineChart, Line, PieChart, Pie, Cell } from "recharts";
import { useTheme } from "../App";

type AnalysisState = "idle" | "processing" | "done" | "clarification" | "error";

interface AIAnalyticsProps {
  initialQuery?: string;
  onAsk?: (question: string) => void;
  analysisResult?: any;
  goalStatus?: string;
  goalResult?: any;
  goalError?: string;
  loading?: boolean;
}

const CHART_COLORS = ["#4F46E5", "#059669", "#F59E0B", "#EC4899", "#06B6D4", "#8B5CF6", "#EF4444", "#14B8A6"];

// Dynamic suggestions from the actual analysis result — fully database-independent.
function getDynamicSuggestions(goalResult: any): string[] {
  const fromResult = goalResult?.suggestedQuestions || goalResult?.suggested_questions || [];
  if (fromResult.length > 0) {
    return fromResult.slice(0, 6);
  }
  return [
    "How many total records are in the connected data?",
    "What is the total of the main numeric measure?",
    "Which categories or segments appear most frequently?",
    "How has the key metric changed over time?",
    "What are the top items by value or quantity?",
    "What is the average of the primary measure?",
  ];
}

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
    loading || goalStatus === "loading" ? "processing" :
    goalError ? "error" :
    goalResult?.clarificationRequired ? "clarification" :
    (analysisResult && (goalStatus === "success" || goalResult?.generatedSql)) ||
    (goalResult?.message && goalStatus === "success") ||
    (goalResult?.data && goalStatus === "success") ? "done" :
    "idle";

  const runAnalysis = (q?: string) => {
    const text = q || query;
    if (!text.trim()) return;
    setQuery(text);
    onAsk?.(text);
  };

  const copySQL = () => {
    const sql = goalResult?.generatedSql || goalResult?.sql_used || "";
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  // Extract real data from results
  const sqlUsed = goalResult?.generatedSql || goalResult?.sql_used || "";
  const tableData = goalResult?.data || analysisResult?.data || [];
  const chartData = tableData.slice(0, 12);
  const followUps = goalResult?.suggestedQuestions || goalResult?.suggested_questions || [];

  // Feedback tracking (personalization layer — Section 62)
  const [insightRating, setInsightRating] = useState<"useful" | "not_useful" | null>(null);
  const trackSuggestionClick = async (text: string) => {
    try {
      const token = localStorage.getItem("aria_auth_token");
      if (token) {
        await fetch("/api/feedback/suggestion", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ suggestion_text: text, source: "analytics" }),
        });
      }
    } catch {}
  };
  const rateInsight = async (rating: "useful" | "not_useful") => {
    setInsightRating(rating);
    try {
      const token = localStorage.getItem("aria_auth_token");
      if (token) {
        await fetch("/api/feedback/insight", {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            question: goalResult?.question || query,
            rating,
            category: "analytics",
          }),
        });
      }
    } catch {}
  };

  // Determine chart type from data shape
  const getChartType = () => {
    if (!chartData.length) return "bar";
    const keys = Object.keys(chartData[0]);
    const dateKeys = keys.filter(k => /date|time|month|year|period|day/i.test(k));
    const numKeys = keys.filter(k => {
      const v = chartData[0]?.[k];
      return typeof v === "number" || (typeof v === "string" && !isNaN(Number(v)));
    });
    const catKeys = keys.filter(k => !dateKeys.includes(k) && !numKeys.includes(k));

    if (dateKeys.length && numKeys.length) return "area";
    if (catKeys.length && numKeys.length && chartData.length <= 8) return "pie";
    return "bar";
  };

  const chartType = getChartType();

  // Get X and Y keys for chart
  const getXKey = () => {
    if (!chartData.length) return "";
    const keys = Object.keys(chartData[0]);
    const dateKeys = keys.filter(k => /date|time|month|year|period|day/i.test(k));
    if (dateKeys.length) return dateKeys[0];
    const catKeys = keys.filter(k => {
      const v = chartData[0]?.[k];
      return typeof v === "string" || typeof v === "boolean";
    });
    return catKeys[0] || keys[0];
  };

  const getYKey = () => {
    if (!chartData.length) return "";
    const keys = Object.keys(chartData[0]);
    const xKey = getXKey();
    const numKeys = keys.filter(k => k !== xKey && (typeof chartData[0]?.[k] === "number" || !isNaN(Number(chartData[0]?.[k]))));
    return numKeys[0] || keys.find(k => k !== xKey) || "";
  };

  const xKey = getXKey();
  const yKey = getYKey();

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
            onKeyDown={(e) => e.key === "Enter" && !loading && runAnalysis()}
            placeholder="How many records? What is the total? Which categories rank highest? How has the metric changed over time?"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
            disabled={loading}
          />
          {query && (
            <button onClick={() => { setQuery(""); }} className="text-muted-foreground hover:text-foreground transition-colors">
              <X size={15} />
            </button>
          )}
          <button
            onClick={() => runAnalysis()}
            disabled={loading || !query.trim()}
            className="premium-btn btn-glow flex-shrink-0 px-4 py-1.5 rounded-lg text-xs font-semibold text-white transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            style={{ background: 'var(--gradient-primary)' }}
          >
            {loading ? "Analyzing..." : "Analyze"}
          </button>
        </div>

        {/* Suggested queries */}
        {state === "idle" && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-muted-foreground flex items-center gap-1.5"><Clock size={11} /> Try asking</p>
            <div className="flex flex-wrap gap-2">
              {getDynamicSuggestions(goalResult).map((q) => (
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
          <div className="text-center space-y-1">
            <p className="text-sm font-medium text-foreground">Analyzing your question...</p>
            <p className="text-xs text-muted-foreground">Generating SQL, executing query, and preparing results</p>
          </div>
        </div>
      )}

      {/* Error */}
      {goalError && state === "error" && (
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <div className="flex items-start gap-3">
            <AlertCircle size={16} className="text-negative mt-0.5 flex-shrink-0" />
            <div className="space-y-2">
              <p className="text-sm text-negative font-medium">{goalError}</p>
              <button
                onClick={() => runAnalysis()}
                className="text-xs text-negative/80 hover:text-negative underline transition-colors"
              >
                Try again
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Clarification */}
      {state === "clarification" && goalResult?.clarificationMessage && (
        <div className="bg-card border border-border rounded-xl p-5 space-y-3">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
              <Sparkles size={12} className="text-primary" />
            </div>
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Clarification needed</p>
          </div>
          <p className="text-sm text-foreground leading-relaxed">{goalResult.clarificationMessage}</p>
          <div className="flex flex-wrap gap-2 pt-1">
            {["total sales by month", "top products", "revenue by category"].map((q) => (
              <button
                key={q}
                onClick={() => runAnalysis(q)}
                className="text-xs px-3 py-1.5 bg-secondary hover:bg-secondary/70 border border-border rounded-full text-muted-foreground hover:text-foreground transition-colors"
              >
                {q}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Results */}
      {state === "done" && (
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
                {tableData.length > 0 && <span>Rows: <span className="text-foreground font-medium">{tableData.length}</span></span>}
                {goalResult.confidence && <span>Confidence: <span className="text-positive font-medium">{goalResult.confidence}</span></span>}
              </div>
              {/* Feedback buttons — personalization signal (Section 62) */}
              <div className="flex items-center gap-2 pt-2 border-t border-border">
                <span className="text-[11px] text-muted-foreground">Was this helpful?</span>
                <button
                  onClick={() => rateInsight("useful")}
                  className={`px-2 py-0.5 text-[11px] rounded-md border transition-colors ${insightRating === "useful" ? "bg-positive/10 border-positive/30 text-positive" : "border-border text-muted-foreground hover:text-foreground hover:border-primary/30"}`}
                >
                  Yes
                </button>
                <button
                  onClick={() => rateInsight("not_useful")}
                  className={`px-2 py-0.5 text-[11px] rounded-md border transition-colors ${insightRating === "not_useful" ? "bg-destructive/10 border-destructive/30 text-destructive" : "border-border text-muted-foreground hover:text-foreground hover:border-primary/30"}`}
                >
                  No
                </button>
              </div>
            </div>
          )}

          {/* Visualization */}
          {chartData.length > 0 && xKey && yKey && (
            <div className="bg-card border border-border rounded-xl p-5">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">Visualization</p>
              <ResponsiveContainer width="100%" height={260}>
                {chartType === "area" ? (
                  <AreaChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    />
                    <Area type="monotone" dataKey={yKey} stroke="#4F46E5" fill="#4F46E5" fillOpacity={0.15} strokeWidth={2} />
                  </AreaChart>
                ) : chartType === "pie" ? (
                  <PieChart>
                    <Pie
                      data={chartData}
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      dataKey={yKey}
                      nameKey={xKey}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                      labelLine={false}
                    >
                      {chartData.map((_, i) => (
                        <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                    />
                  </PieChart>
                ) : (
                  <BarChart data={chartData} barSize={36}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
                    <Tooltip
                      contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                      labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
                    />
                    <Bar dataKey={yKey} fill="#4F46E5" radius={[5, 5, 0, 0]} />
                  </BarChart>
                )}
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
                {tableData.length > 0 && (
                  <span className="text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">{tableData.length} rows</span>
                )}
              </div>
              {showTable ? <ChevronUp size={14} className="text-muted-foreground" /> : <ChevronDown size={14} className="text-muted-foreground" />}
            </button>
            {showTable && tableData.length > 0 && (
              <div className="border-t border-border overflow-x-auto max-h-80 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-card">
                    <tr className="border-b border-border">
                      {Object.keys(tableData[0]).map((h) => (
                        <th key={h} className="text-left text-xs font-medium text-muted-foreground px-5 py-3 whitespace-nowrap">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {tableData.slice(0, 50).map((row, i) => (
                      <tr key={i} className={`${i < Math.min(tableData.length, 50) - 1 ? "border-b border-border" : ""} hover:bg-secondary/30 transition-colors`}>
                        {Object.values(row).map((val: any, j) => (
                          <td key={j} className="px-5 py-3 text-foreground whitespace-nowrap">
                            {typeof val === "number" ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(val) : String(val ?? "—")}
                          </td>
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
                        {copied ? <><CheckCircle size={12} className="text-positive" /> Copied!</> : <><Copy size={12} /> Copy</>}
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
                    onClick={() => { trackSuggestionClick(q); setQuery(q); runAnalysis(q); }}
                    className="premium-card flex items-center justify-between bg-card border border-border rounded-xl px-4 py-3 hover:border-primary/40 text-left group"
                  >
                    <p className="text-sm text-foreground group-hover:text-primary transition-colors">{q}</p>
                    <ArrowRight size={13} className="text-muted-foreground group-hover:text-primary transition-colors ml-2 flex-shrink-0" />
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Provenance — source, table, column, SQL trace */}
          {goalResult?.provenance && (
            <div className="bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <GitBranch size={14} className="text-muted-foreground" />
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Source & Provenance</p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div className="space-y-1">
                  <p className="text-muted-foreground">Source</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.source || "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Type</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.source_type || "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Tables</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.tables?.join(", ") || "—"}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Rows</p>
                  <p className="text-foreground font-medium">{goalResult.provenance.row_count?.toLocaleString() || "—"}</p>
                </div>
              </div>
              {goalResult.provenance.columns?.length > 0 && (
                <div className="text-xs">
                  <p className="text-muted-foreground mb-1">Columns used</p>
                  <div className="flex flex-wrap gap-1.5">
                    {goalResult.provenance.columns.map((col: string) => (
                      <span key={col} className="px-2 py-0.5 bg-muted rounded text-foreground">{col}</span>
                    ))}
                  </div>
                </div>
              )}
              {goalResult.provenance.join_path?.length > 0 && (
                <div className="text-xs">
                  <p className="text-muted-foreground mb-1">Join path</p>
                  <p className="text-foreground font-mono text-[11px]">
                    {goalResult.provenance.join_path.map((j: any) => `${j.from}.${j.from_col} = ${j.to}.${j.to_col}`).join(" → ")}
                  </p>
                </div>
              )}
              {goalResult.conversationId && (
                <div className="flex items-center gap-4 text-[11px] text-muted-foreground pt-1 border-t border-border">
                  <span>Conversation: {goalResult.conversationId.split("_").slice(-1)[0]}</span>
                  {goalResult.turnNumber && <span>Turn: {goalResult.turnNumber}</span>}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
