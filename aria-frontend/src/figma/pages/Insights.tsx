import { useState, useEffect, useCallback } from "react";
import { Filter, Bookmark, ChevronDown, Share2, MessageSquare, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { useTheme } from "../App";

const API_BASE = "";

interface InsightEvidence {
  observations?: string[];
  supportingMetrics?: string[];
  sampleSize?: number;
  baseline?: number;
  currentValue?: number;
  changePercent?: number;
  statisticalTest?: string;
}

interface InsightBusinessImpact {
  value?: number;
  direction?: "positive" | "negative" | "neutral";
  explanation?: string;
}

interface InsightRecommendation {
  question?: string;
  metric?: string;
  dimensions?: string[];
}

interface InsightViz {
  type?: string;
  data?: any[];
}

interface Insight {
  id: string;
  type: string;
  severity: string;
  title: string;
  description: string;
  metric: string;
  metricValue?: number;
  previousValue?: number;
  magnitude: string;
  confidence: number;
  detectedAt: string;
  affectedPeriod: string;
  tags: string[];
  evidence?: InsightEvidence;
  businessImpact?: InsightBusinessImpact;
  recommendedNextAnalysis?: InsightRecommendation;
  visualization?: InsightViz;
  source?: { tables: string[]; columns: string[] };
}

const allTypes = ["All", "Growth", "Anomaly", "Opportunity", "Risk", "Trend", "Decline", "Correlation"];
const allSeverities = ["All", "High", "Medium", "Low"];

const typeColor: Record<string, string> = {
  Growth: "text-positive bg-positive/10 border-positive/20",
  Anomaly: "text-negative bg-negative/10 border-negative/20",
  Opportunity: "text-warning bg-warning/10 border-warning/20",
  Risk: "text-negative bg-negative/10 border-negative/20",
  Trend: "text-primary bg-primary/10 border-primary/20",
  Decline: "text-negative bg-negative/10 border-negative/20",
  Correlation: "text-muted-foreground bg-muted border-border",
};

const severityRing: Record<string, string> = {
  high: "bg-negative",
  medium: "bg-warning",
  low: "bg-positive",
};

function MiniChart({ viz }: { viz?: InsightViz }) {
  if (!viz?.data?.length) return null;
  const data = viz.data;
  const vals = data.map((d: any) => d.value ?? d.val ?? 0);
  const max = Math.max(...vals);
  const min = Math.min(...vals);
  const range = max - min || 1;
  const w = 120;
  const h = 32;
  const pts = vals.map((v: number, i: number) => {
    const x = (i / (vals.length - 1)) * w;
    const y = h - ((v - min) / range) * h;
    return `${x},${y}`;
  }).join(" ");

  if (viz.type === "bar") {
    return (
      <div className="flex items-end gap-px" style={{ width: w, height: h }}>
        {vals.slice(-8).map((v: number, i: number) => (
          <div key={i} className="flex-1 bg-primary/40 rounded-t" style={{ height: `${((v - min) / range) * 100}%`, minHeight: 2 }} />
        ))}
      </div>
    );
  }

  return (
    <svg width={w} height={h} className="overflow-visible">
      <polyline fill="none" stroke="currentColor" strokeWidth="1.5" className="text-primary/60" points={pts} />
    </svg>
  );
}

function ObservationBlock({ evidence }: { evidence?: InsightEvidence }) {
  if (!evidence?.observations?.length) return null;
  return (
    <div className="bg-card border border-border rounded-lg p-3 space-y-2">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Observations</p>
      {evidence.observations.map((obs: string, i: number) => (
        <p key={i} className="text-xs text-foreground leading-relaxed">{obs}</p>
      ))}
    </div>
  );
}

function EvidenceBlock({ evidence }: { evidence?: InsightEvidence }) {
  if (!evidence) return null;
  return (
    <div className="bg-card border border-border rounded-lg p-3 space-y-2">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Evidence</p>
      {evidence.supportingMetrics?.map((m: string, i: number) => (
        <div key={i} className="text-xs"><span className="text-muted-foreground">• </span><span className="text-foreground">{m}</span></div>
      ))}
      {evidence.sampleSize != null && (
        <div className="text-xs"><span className="text-muted-foreground">Sample: </span><span className="text-foreground font-medium">{evidence.sampleSize} periods</span></div>
      )}
      {evidence.changePercent != null && (
        <div className="text-xs"><span className="text-muted-foreground">Change: </span>
          <span className={`font-medium ${evidence.changePercent >= 0 ? "text-positive" : "text-negative"}`}>
            {evidence.changePercent >= 0 ? "+" : ""}{evidence.changePercent.toFixed(1)}%
          </span>
        </div>
      )}
    </div>
  );
}

function BusinessImpactBlock({ impact }: { impact?: InsightBusinessImpact }) {
  if (!impact) return null;
  return (
    <div className="bg-card border border-border rounded-lg p-3 space-y-2">
      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Business Impact</p>
      <p className="text-xs text-foreground leading-relaxed">{impact.explanation}</p>
      {impact.value != null && impact.value !== 0 && (
        <div className="text-xs"><span className="text-muted-foreground">Estimated impact: </span>
          <span className={`font-medium ${impact.direction === "positive" ? "text-positive" : impact.direction === "negative" ? "text-negative" : "text-foreground"}`}>
            {impact.direction === "positive" ? "+" : ""}{impact.value >= 0 ? "$" : "-$"}{Math.abs(impact.value).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </span>
        </div>
      )}
    </div>
  );
}

export default function Insights({
  insightResult = null,
  insightStatus = "idle",
  insightError = "",
  onAskQuestion,
}: {
  insightResult?: any;
  insightStatus?: string;
  insightError?: string;
  onAskQuestion?: (question: string) => void;
}) {
  const { isDark } = useTheme();
  const [typeFilter, setTypeFilter] = useState("All");
  const [severityFilter, setSeverityFilter] = useState("All");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [savedIds, setSavedIds] = useState<string[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchInsights = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch(`${API_BASE}/api/insights`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.ok && data.insights) {
        setInsights(data.insights);
      } else {
        setInsights([]);
        if (data.detail) setError(data.detail);
      }
    } catch (e: any) {
      setError(e.message || "Failed to load insights");
      setInsights([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchSaved = useCallback(async () => {
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch(`${API_BASE}/api/insights/saved`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const data = await res.json();
      if (data.ok && data.saved) {
        setSavedIds(data.saved.map((s: any) => s.insight_id));
      }
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  }, []);

  useEffect(() => {
    fetchInsights();
    fetchSaved();
  }, [fetchInsights, fetchSaved]);

  // Also use props if provided (for backward compatibility)
  const propInsights = insightResult?.keyInsights || [];
  const allInsights = insights.length > 0 ? insights : propInsights;

  const filtered = allInsights.filter((ins: any) => {
    const typeOk = typeFilter === "All" || ins.type === typeFilter;
    const sevOk = severityFilter === "All" || (ins.severity || "").toLowerCase() === severityFilter.toLowerCase();
    return typeOk && sevOk;
  });

  const toggleSave = async (ins: Insight) => {
    const isSaved = savedIds.includes(ins.id);
    const token = localStorage.getItem("aria_auth_token");
    try {
      if (isSaved) {
        await fetch(`${API_BASE}/api/insights/save/${ins.id}`, {
          method: "DELETE",
          headers: { Authorization: `Bearer ${token}` },
        });
        setSavedIds((s) => s.filter((id) => id !== ins.id));
      } else {
        await fetch(`${API_BASE}/api/insights/save`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            insight_id: ins.id,
            title: ins.title,
            insight_type: ins.type,
            severity: ins.severity,
            metric: ins.metric,
            insight_payload: ins,
          }),
        });
        setSavedIds((s) => [...s, ins.id]);
      }
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
  };

  const handleShare = async (ins: Insight) => {
    const text = `${ins.title}\n\n${ins.description}\n\nMetric: ${ins.metric}\nConfidence: ${ins.confidence}%`;
    if (navigator.share) {
      try {
        await navigator.share({ title: ins.title, text });
      } catch (err) { console.debug("[ARIA] background request failed:", err); }
    } else {
      await navigator.clipboard.writeText(text);
    }
  };

  const handleAskAria = async (ins: Insight) => {
    const question = ins.recommendedNextAnalysis?.question || ins.description;
    try {
      const token = localStorage.getItem("aria_auth_token");
      await fetch(`${API_BASE}/api/insights/${ins.id}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question, insight_id: ins.id }),
      });
    } catch (err) { console.debug("[ARIA] background request failed:", err); }
    // Primary path: run the question in AI Analytics with full context.
    if (onAskQuestion) {
      onAskQuestion(question);
      return;
    }
    // Legacy fallback (no handler wired): prefill for AI Analytics to pick up.
    sessionStorage.setItem("aria_prefill_question", question);
    window.location.hash = "#/ai-analytics";
  };

  if (loading) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-12">
          <Loader2 size={24} className="animate-spin text-primary mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">Analyzing your data for insights...</p>
        </div>
      </div>
    );
  }

  if (error && !allInsights.length) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <p className="text-sm text-negative font-medium">{error}</p>
          <button onClick={fetchInsights} className="mt-2 text-xs text-primary hover:underline">Try again</button>
        </div>
      </div>
    );
  }

  if (!allInsights.length) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div>
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-foreground tracking-tight">Insights</h2>
              <p className="text-sm text-muted-foreground mt-0.5">Automatically discovered patterns in your business data.</p>
            </div>
            <button onClick={fetchInsights} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
              <RefreshCw size={14} />
            </button>
          </div>
        </div>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-muted-foreground">No insights available yet.</p>
          <p className="text-xs text-muted-foreground mt-2">Connect a database to automatically discover patterns.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-6">
      <div className="flex items-center justify-between animate-fade-in">
        <div>
          <h2 className="text-xl font-bold text-foreground tracking-tight">Insights</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Automatically discovered patterns in your business data.</p>
        </div>
        <button onClick={fetchInsights} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground bg-card border border-border rounded-lg px-3 py-2">
          <Filter size={12} /> Filters
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {allTypes.map((t) => (
            <button key={t} onClick={() => setTypeFilter(t)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                typeFilter === t ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground border-border hover:text-foreground"
              }`}>{t}</button>
          ))}
        </div>
        <div className="w-px h-5 bg-border" />
        <div className="flex gap-1.5 flex-wrap">
          {allSeverities.map((s) => (
            <button key={s} onClick={() => setSeverityFilter(s)}
              className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                severityFilter === s ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground border-border hover:text-foreground"
              }`}>{s}</button>
          ))}
        </div>
        <span className="ml-auto text-xs text-muted-foreground">{filtered.length} insights</span>
      </div>

      <div className="space-y-4 stagger-children">
        {filtered.map((ins: any, idx: number) => {
          const expanded = expandedId === ins.id;
          const isSaved = savedIds.includes(ins.id);

          return (
            <div key={ins.id || idx} className="premium-card bg-card border border-border rounded-xl overflow-hidden cursor-default">
              <div className="p-5">
                <div className="flex gap-4">
                  <div className={`mt-1 w-2.5 h-2.5 rounded-full flex-shrink-0 ${severityRing[ins.severity] || "bg-primary"}`} />
                  <div className="flex-1 min-w-0 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <h3 className="text-sm font-semibold text-foreground leading-snug">{ins.title}</h3>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${typeColor[ins.type] || "text-primary bg-primary/10 border-primary/20"}`}>
                            {ins.type}
                          </span>
                          {ins.confidence != null && (
                            <span className="text-[10px] text-muted-foreground">{ins.confidence}% confidence</span>
                          )}
                          {ins.affectedPeriod && (
                            <span className="text-[10px] text-muted-foreground">{ins.affectedPeriod}</span>
                          )}
                        </div>
                      </div>
                      {ins.visualization && (
                        <div className="flex-shrink-0 opacity-70">
                          <MiniChart viz={ins.visualization} />
                        </div>
                      )}
                    </div>

                    <p className="text-sm text-muted-foreground leading-relaxed">{ins.description}</p>

                    {ins.magnitude && (
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold ${ins.magnitude.startsWith("+") ? "text-positive" : ins.magnitude.startsWith("-") ? "text-negative" : "text-foreground"}`}>
                          {ins.magnitude}
                        </span>
                      </div>
                    )}

                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => toggleSave(ins)}
                          className={`p-1.5 rounded-lg transition-colors ${isSaved ? "text-primary" : "text-muted-foreground hover:text-foreground"} hover:bg-secondary`}
                        >
                          <Bookmark size={13} fill={isSaved ? "currentColor" : "none"} />
                        </button>
                        <button
                          onClick={() => handleShare(ins)}
                          className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                        >
                          <Share2 size={13} />
                        </button>
                        <button
                          onClick={() => handleAskAria(ins)}
                          className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                          title="Ask ARIA about this insight"
                        >
                          <MessageSquare size={13} />
                        </button>
                        <button
                          onClick={() => setExpandedId(expanded ? null : ins.id)}
                          className="text-xs text-primary hover:underline flex items-center gap-1 ml-1"
                        >
                          {expanded ? "Collapse" : "Explore"} <ChevronDown size={12} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {expanded && (
                <div className="border-t border-border bg-muted/30 px-5 py-5 pl-9 space-y-3">
                  <ObservationBlock evidence={ins.evidence} />
                  <EvidenceBlock evidence={ins.evidence} />
                  <BusinessImpactBlock impact={ins.businessImpact} />

                  {ins.recommendedNextAnalysis?.question && (
                    <div className="bg-card border border-border rounded-lg p-3 space-y-2">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Recommended Next Analysis</p>
                      <p className="text-xs text-foreground leading-relaxed">{ins.recommendedNextAnalysis.question}</p>
                      <button
                        onClick={() => handleAskAria(ins)}
                        className="text-xs text-primary hover:underline flex items-center gap-1"
                      >
                        <ExternalLink size={10} /> Ask ARIA
                      </button>
                    </div>
                  )}

                  {ins.source && (
                    <div className="text-[10px] text-muted-foreground">
                      Source: {ins.source.tables?.join(", ")}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {filtered.length === 0 && allInsights.length > 0 && (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-4">
            <Filter size={20} className="text-muted-foreground" />
          </div>
          <p className="text-sm font-medium text-foreground">No insights match your filters</p>
          <p className="text-sm text-muted-foreground mt-1">Try adjusting the type or severity filter</p>
          <button onClick={() => { setTypeFilter("All"); setSeverityFilter("All"); }} className="mt-4 text-xs text-primary hover:underline">
            Clear filters
          </button>
        </div>
      )}
    </div>
  );
}
