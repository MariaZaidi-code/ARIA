import { useState, useEffect, useCallback } from "react";
import { CheckCircle, Bookmark, MessageSquare, ChevronDown, ChevronUp, Loader2, RefreshCw } from "lucide-react";

interface PrescriptionProps {
  insightResult?: any;
  onAskQuestion?: (question: string) => void;
}

const priorityStyle: Record<string, string> = {
  high: "text-negative bg-negative/10 border-negative/20",
  medium: "text-warning bg-warning/10 border-warning/20",
  low: "text-positive bg-positive/10 border-positive/20",
};

const priorities = ["high", "medium", "low"];

export default function Prescription({ insightResult = null, onAskQuestion }: PrescriptionProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [saved, setSaved] = useState<string[]>([]);
  const [prescriptions, setPrescriptions] = useState<any[]>([]);
  const [impactNote, setImpactNote] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Try to get recommendations from insightResult first (from InsightAgent)
  const propRecommendations = insightResult?.recommendations || [];

  const fetchPrescriptions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/prescription/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (data.ok && data.prescriptions) {
        const actions = data.prescriptions.actions || [];
        const mapped = actions.map((action: string, i: number) => ({
          title: action,
          description: action,
          priority: priorities[i % 3],
          evidence: null,
        }));
        setPrescriptions(mapped);
        setImpactNote(data.prescriptions.impact_note || "");
      } else {
        setPrescriptions([]);
        setImpactNote("");
      }
    } catch (e: any) {
      setError(e.message || "Failed to load prescriptions");
      setPrescriptions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Use insightResult recommendations if available, otherwise fetch from API
    if (propRecommendations.length > 0) {
      setPrescriptions(propRecommendations);
    } else {
      fetchPrescriptions();
    }
  }, [propRecommendations.length, fetchPrescriptions]);

  const recommendations = prescriptions;

  if (loading) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Prescription</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Turn insights into actionable decisions.</p>
        </div>
        <div className="mt-8 text-center py-12">
          <Loader2 size={24} className="animate-spin text-primary mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">Generating recommendations...</p>
        </div>
      </div>
    );
  }

  if (error && !recommendations.length) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Prescription</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Turn insights into actionable decisions.</p>
        </div>
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5 mt-4">
          <p className="text-sm text-negative font-medium">{error}</p>
          <button onClick={fetchPrescriptions} className="mt-2 text-xs text-primary hover:underline">Try again</button>
        </div>
      </div>
    );
  }

  if (!recommendations.length) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-foreground tracking-tight">Prescription</h2>
            <p className="text-sm text-muted-foreground mt-0.5">Turn insights into actionable decisions.</p>
          </div>
          <button onClick={fetchPrescriptions} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
            <RefreshCw size={14} />
          </button>
        </div>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-muted-foreground">No recommendations available yet.</p>
          <p className="text-xs text-muted-foreground mt-2">Connect a database to generate actionable prescriptions.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="flex items-center justify-between animate-fade-in">
        <div>
          <h2 className="text-xl font-bold text-foreground tracking-tight">Prescription</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Turn insights into actionable decisions.</p>
        </div>
        <button onClick={fetchPrescriptions} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
          <RefreshCw size={14} />
        </button>
      </div>

      <div className="flex gap-4 text-sm text-muted-foreground">
        <span><span className="text-foreground font-semibold">{recommendations.length}</span> recommendations ·</span>
        <span><span className="text-positive font-semibold">{recommendations.filter((r: any) => (r.priority || "medium").toLowerCase() === "high").length}</span> high priority ·</span>
        <span><span className="text-foreground font-semibold">{accepted.length}</span> accepted</span>
      </div>
      {impactNote && (
        <p className="text-xs text-muted-foreground bg-secondary/50 border border-border rounded-lg px-3 py-2">{impactNote}</p>
      )}

      <div className="space-y-4">
        {recommendations.map((rec, idx) => {
          const isExpanded = expandedId === String(idx);
          const isAccepted = accepted.includes(String(idx));
          const isSaved = saved.includes(String(idx));
          const priority = rec.priority || "medium";

          return (
            <div key={idx} className={`premium-card bg-card border rounded-xl overflow-hidden cursor-default ${isAccepted ? "border-positive/40" : "border-border"}`}>
              <div className="p-5 space-y-3">
                <div className="flex items-start gap-3">
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border capitalize ${priorityStyle[priority.toLowerCase()] || priorityStyle.medium}`}>
                        {priority} Priority
                      </span>
                      {isAccepted && (
                        <span className="text-xs text-positive bg-positive/10 border border-positive/20 px-2 py-0.5 rounded-full flex items-center gap-1">
                          <CheckCircle size={10} /> Accepted
                        </span>
                      )}
                    </div>
                    <h3 className="text-sm font-semibold text-foreground leading-snug">{rec.title || rec.description}</h3>
                    <p className="text-sm text-muted-foreground leading-relaxed">{rec.description}</p>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-2">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setAccepted((a) => isAccepted ? a.filter((x) => x !== String(idx)) : [...a, String(idx)])}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                        isAccepted
                          ? "bg-positive/10 text-positive border border-positive/20"
                          : "bg-primary text-primary-foreground hover:opacity-90"
                      }`}
                    >
                      <CheckCircle size={12} /> {isAccepted ? "Accepted" : "Accept"}
                    </button>
                    <button
                      onClick={() => setSaved((s) => isSaved ? s.filter((x) => x !== String(idx)) : [...s, String(idx)])}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                        isSaved ? "text-primary border-primary/40 bg-primary/5" : "text-muted-foreground border-border hover:text-foreground hover:bg-secondary"
                      }`}
                    >
                      <Bookmark size={12} fill={isSaved ? "currentColor" : "none"} /> Save
                    </button>
                    {onAskQuestion && (
                      <button
                        onClick={() => onAskQuestion(`What data supports this recommendation: ${rec.title || rec.description}`)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border border-border text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                      >
                        <MessageSquare size={12} /> Ask ARIA
                      </button>
                    )}
                  </div>
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : String(idx))}
                    className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1 transition-colors"
                  >
                    Evidence {isExpanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  </button>
                </div>
              </div>

              {isExpanded && (
                <div className="border-t border-border bg-muted/30 px-5 py-5 space-y-3">
                  <p className="text-sm text-foreground leading-relaxed">{rec.description}</p>
                  {rec.evidence && (
                    <div className="bg-card border border-border rounded-lg p-3 space-y-2">
                      <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Supporting Evidence</p>
                      {rec.evidence.metric && <div className="text-xs"><span className="text-muted-foreground">Metric: </span><span className="text-foreground font-medium">{rec.evidence.metric}</span></div>}
                      {rec.evidence.impact && <div className="text-xs"><span className="text-muted-foreground">Estimated Impact: </span><span className="text-foreground font-medium">{rec.evidence.impact}</span></div>}
                      {rec.evidence.confidence != null && <div className="text-xs"><span className="text-muted-foreground">Confidence: </span><span className="text-foreground font-medium">{String(rec.evidence.confidence)}%</span></div>}
                    </div>
                  )}
                  <div className="grid grid-cols-3 gap-3 text-center">
                    {rec.impact && <div className="bg-card border border-border rounded-lg p-2"><p className="text-[10px] text-muted-foreground uppercase">Impact</p><p className="text-xs font-semibold text-foreground capitalize">{rec.impact}</p></div>}
                    {rec.difficulty && <div className="bg-card border border-border rounded-lg p-2"><p className="text-[10px] text-muted-foreground uppercase">Difficulty</p><p className="text-xs font-semibold text-foreground capitalize">{rec.difficulty}</p></div>}
                    {rec.risk && <div className="bg-card border border-border rounded-lg p-2"><p className="text-[10px] text-muted-foreground uppercase">Risk</p><p className="text-xs font-semibold text-foreground capitalize">{rec.risk}</p></div>}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
