import { useState } from "react";
import { Filter, Bookmark, ChevronDown } from "lucide-react";
import { useTheme } from "../App";

interface InsightsProps {
  insightResult?: any;
  insightStatus?: string;
  insightError?: string;
}

const allTypes = ["All", "Growth", "Anomaly", "Opportunity", "Risk", "Trend", "Decline", "Correlation"];
const allSeverities = ["All", "High", "Medium", "Low"];

const typeColor: Record<string, string> = {
  Growth: "text-positive bg-positive/10 border-positive/20",
  Anomaly: "text-negative bg-negative/10 border-negative/20",
  Opportunity: "text-warning bg-warning/10 border-warning/20",
  Risk: "text-negative bg-negative/10 border-negative/20",
  Trend: "text-primary bg-primary/10 border-primary/20",
};

const severityRing: Record<string, string> = {
  high: "bg-negative",
  medium: "bg-warning",
  low: "bg-positive",
};

export default function Insights({
  insightResult = null,
  insightStatus = "idle",
  insightError = "",
}: InsightsProps) {
  const { isDark } = useTheme();
  const [typeFilter, setTypeFilter] = useState("All");
  const [severityFilter, setSeverityFilter] = useState("All");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [saved, setSaved] = useState<string[]>([]);

  const insights = insightResult?.keyInsights || [];

  const filtered = insights.filter((ins: any) => {
    const typeOk = typeFilter === "All" || ins.impact === typeFilter || ins.type === typeFilter;
    const sevOk = severityFilter === "All" || (ins.impact && ins.impact.toLowerCase() === severityFilter.toLowerCase());
    return typeOk && sevOk;
  });

  if (insightStatus === "running") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-12">
          <p className="text-muted-foreground">Generating insights...</p>
        </div>
      </div>
    );
  }

  if (insightError) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <p className="text-sm text-negative font-medium">{insightError}</p>
        </div>
      </div>
    );
  }

  if (!insights.length) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Insights</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Automatically discovered patterns in your business data.</p>
        </div>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-muted-foreground">No insights available yet.</p>
          <p className="text-xs text-muted-foreground mt-2">Run an analysis to generate AI-powered insights.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-6">
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">Insights</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Automatically discovered patterns in your business data.</p>
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
          const expanded = expandedId === String(idx);
          const isSaved = saved.includes(String(idx));

          return (
            <div key={idx} className="premium-card bg-card border border-border rounded-xl overflow-hidden cursor-default">
              <div className="p-5">
                <div className="flex gap-4">
                  <div className={`mt-1 w-2.5 h-2.5 rounded-full flex-shrink-0 ${severityRing[ins.impact] || "bg-primary"}`} />
                  <div className="flex-1 min-w-0 space-y-3">
                    <div className="flex items-start justify-between gap-3">
                      <div className="space-y-1">
                        <h3 className="text-sm font-semibold text-foreground leading-snug">{ins.title}</h3>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${typeColor[ins.impact] || typeColor[ins.type] || "text-primary bg-primary/10 border-primary/20"}`}>
                            {ins.impact || ins.type || "Insight"}
                          </span>
                        </div>
                      </div>
                    </div>

                    <p className="text-sm text-muted-foreground leading-relaxed">{ins.description}</p>

                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => setSaved((s) => isSaved ? s.filter((x) => x !== String(idx)) : [...s, String(idx)])}
                          className={`p-1.5 rounded-lg transition-colors ${isSaved ? "text-primary" : "text-muted-foreground hover:text-foreground"} hover:bg-secondary`}
                        >
                          <Bookmark size={13} fill={isSaved ? "currentColor" : "none"} />
                        </button>
                        <button
                          onClick={() => setExpandedId(expanded ? null : String(idx))}
                          className="text-xs text-primary hover:underline flex items-center gap-1 ml-1"
                        >
                          {expanded ? "Collapse" : "Details"} <ChevronDown size={12} className={`transition-transform ${expanded ? "rotate-180" : ""}`} />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {expanded && (
                <div className="border-t border-border bg-muted/30 px-5 py-5 pl-9">
                  <p className="text-sm text-foreground">{ins.description}</p>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {filtered.length === 0 && (
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
