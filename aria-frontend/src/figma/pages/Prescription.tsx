import { useState } from "react";
import { CheckCircle, Bookmark, MessageSquare, ChevronDown, ChevronUp, AlertTriangle, TrendingUp, TrendingDown, Minus } from "lucide-react";

interface PrescriptionProps {
  insightResult?: any;
}

const priorityStyle: Record<string, string> = {
  high: "text-negative bg-negative/10 border-negative/20",
  medium: "text-warning bg-warning/10 border-warning/20",
  low: "text-positive bg-positive/10 border-positive/20",
};

export default function Prescription({ insightResult = null }: PrescriptionProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string[]>([]);
  const [saved, setSaved] = useState<string[]>([]);

  // Extract recommendations from insight result
  const recommendations = insightResult?.recommendations || [];

  // Show empty state if no recommendations
  if (!recommendations.length) {
    return (
      <div className="p-6 max-w-4xl mx-auto">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Prescription</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Turn insights into actionable decisions.</p>
        </div>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-muted-foreground">No recommendations available yet.</p>
          <p className="text-xs text-muted-foreground mt-2">Run an analysis to generate actionable prescriptions.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">Prescription</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Turn insights into actionable decisions.</p>
      </div>

      <div className="flex gap-4 text-sm text-muted-foreground">
        <span className="text-foreground font-semibold">{recommendations.length}</span> recommendations ·
        <span className="text-foreground font-semibold">{accepted.length}</span> accepted
      </div>

      <div className="space-y-4">
        {recommendations.map((rec, idx) => {
          const isExpanded = expandedId === String(idx);
          const isAccepted = accepted.includes(String(idx));
          const isSaved = saved.includes(String(idx));
          const priority = rec.priority || "medium";

          return (
            <div key={idx} className={`premium-card bg-card border rounded-xl overflow-hidden cursor-default ${isAccepted ? "border-positive/40" : "border-border"}`}>
              <div className="p-5 space-y-3">
                {/* Header */}
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

                {/* Actions */}
                <div className="flex items-center justify-between pt-2">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setAccepted((a) => isAccepted ? a.filter((x) => x !== String(idx)) : [...a, String(idx)])}
                      className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                        isAccepted
                          ? "bg-positive text-white border-positive"
                          : "bg-card text-foreground border-border hover:border-positive"
                      }`}
                    >
                      {isAccepted ? "Accepted" : "Accept"}
                    </button>
                    <button
                      onClick={() => setSaved((s) => isSaved ? s.filter((x) => x !== String(idx)) : [...s, String(idx)])}
                      className={`p-1.5 rounded-lg transition-colors ${isSaved ? "text-primary" : "text-muted-foreground hover:text-foreground"} hover:bg-secondary`}
                    >
                      <Bookmark size={13} fill={isSaved ? "currentColor" : "none"} />
                    </button>
                  </div>
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : String(idx))}
                    className="text-xs text-primary hover:underline flex items-center gap-1"
                  >
                    {isExpanded ? "Collapse" : "Details"} <ChevronDown size={12} className={`transition-transform ${isExpanded ? "rotate-180" : ""}`} />
                  </button>
                </div>
              </div>

              {/* Expanded detail */}
              {isExpanded && (
                <div className="border-t border-border bg-muted/30 px-5 py-5">
                  <p className="text-sm text-foreground leading-relaxed">{rec.description}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
