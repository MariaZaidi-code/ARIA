import { useState, useEffect, useCallback, useMemo } from "react";
import { Filter, Bookmark, ChevronDown, ChevronRight, Share2, MessageSquare, FlaskConical, TrendingUp, ClipboardList, RefreshCw, Loader2, AlertTriangle, Database, Clock, Sparkles } from "lucide-react";
import { useTheme } from "../App";

/* =====================================================================
   ARIA Insights — evidence-driven insight discovery workspace
   Spec: insight.docx (OBSERVATION → EVIDENCE → BUSINESS IMPACT →
   RECOMMENDED NEXT ANALYSIS). Inspo: left investigation feed (Freddy) +
   right evidence workspace + confidence dots + "See What's Driving This".
   ONLY this page is touched. All values come from GET /api/insights
   (deterministic detectors). LLM never calculates numbers here.
   ===================================================================== */

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

/* ---- Spec §4/§9 taxonomy: one insight can surface under several filters
   (e.g. a Growth insight is both a Trend and a Performance signal), so no
   filter looks empty while sibling views have content. ---- */
type Category = "trends" | "anomalies" | "performance" | "relationships" | "opportunities" | "risks";

const FILTERS: { id: string; label: string; cat: Category | "all" }[] = [
  { id: "all", label: "All", cat: "all" },
  { id: "trends", label: "Trends", cat: "trends" },
  { id: "anomalies", label: "Anomalies", cat: "anomalies" },
  { id: "performance", label: "Performance", cat: "performance" },
  { id: "relationships", label: "Relationships", cat: "relationships" },
  { id: "opportunities", label: "Opportunities", cat: "opportunities" },
  { id: "risks", label: "Risks", cat: "risks" },
];

function matchesFilter(type: string, filter: string): boolean {
  if (filter === "all") return true;
  const t = (type || "").toLowerCase();
  switch (filter) {
    case "trends": return t.includes("trend") || t.includes("growth") || t.includes("decline");
    case "performance": return t.includes("growth") || t.includes("decline");
    case "anomalies": return t.includes("anomal");
    case "relationships": return t.includes("correl") || t.includes("relation");
    case "opportunities": return t.includes("opportunit") || t.includes("growth");
    case "risks": return t.includes("risk") || t.includes("decline");
    default: return true;
  }
}

function primaryCategory(type: string): Category {
  const t = (type || "").toLowerCase();
  if (t.includes("anomal")) return "anomalies";
  if (t.includes("opportunit")) return "opportunities";
  if (t.includes("risk")) return "risks";
  if (t.includes("correl") || t.includes("relation")) return "relationships";
  if (t.includes("growth") || t.includes("decline") || t.includes("perform")) return "performance";
  return "trends";
}

function typeLabel(type: string): string {
  const t = (type || "").toUpperCase();
  if (t === "CORRELATION") return "RELATIONSHIP";
  return t || "TREND";
}

/* ---- Trust (§12): confidence only from computed evidence ---- */
function confidenceInfo(conf?: number): { label: string; dots: number; tone: string } {
  const c = typeof conf === "number" ? conf : -1;
  if (c >= 75) return { label: "High confidence", dots: 3, tone: "text-positive" };
  if (c >= 50) return { label: "Moderate confidence", dots: 2, tone: "text-primary" };
  if (c >= 30) return { label: "Limited evidence", dots: 1, tone: "text-warning" };
  return { label: "Insufficient data", dots: 0, tone: "text-muted-foreground" };
}

function ConfidenceDots({ conf }: { conf?: number }) {
  const info = confidenceInfo(conf);
  return (
    <span className="inline-flex items-center gap-1.5" title={typeof conf === "number" ? `${info.label} (${conf}%)` : info.label}>
      <span className="flex items-center gap-0.5" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span key={i} className={`w-1.5 h-1.5 rounded-full ${i < info.dots ? "bg-positive" : "bg-border"}`} />
        ))}
      </span>
      <span className={`text-[10px] font-medium ${info.tone}`}>{info.label}</span>
    </span>
  );
}

function severityAccent(sev: string): string {
  const s = (sev || "").toLowerCase();
  if (s === "high") return "#DC2626";
  if (s === "medium") return "#D97706";
  return "#4F46E5";
}

const fmtMoney = (v?: number | null) => {
  if (v === null || v === undefined || isNaN(Number(v))) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `$${(n / 1_000).toFixed(0)}K`;
  return `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
};

/* ================= Dynamic evidence chart (SVG, no dummy data) ===============
   Trend/Growth/Decline/Risk → line · Opportunity/Performance/Segment → bar
   Relationship/Correlation → scatter · Anomaly → line with highlighted point
   Returns null on missing/unsupported data so callers show a graceful note. */
function EvidenceChart({ ins }: { ins: Insight }) {
  const viz = ins.visualization;
  const data = viz?.data || [];
  const vtype = (viz?.type || "").toLowerCase();
  const cat = primaryCategory(ins.type);
  if (!data.length) return null;

  const W = 560, H = 220, PL = 44, PR = 12, PT = 14, PB = 28;
  const iw = W - PL - PR, ih = H - PT - PB;

  // Scatter: correlation payload {table1, table2} or {x,y}
  if (vtype === "scatter" || cat === "relationships") {
    const pts = data
      .map((d: any) => ({ x: Number(d.table1 ?? d.x), y: Number(d.table2 ?? d.y), l: String(d.period ?? d.label ?? "") }))
      .filter((p: any) => !isNaN(p.x) && !isNaN(p.y));
    if (pts.length < 2) return null;
    const xs = pts.map((p: any) => p.x), ys = pts.map((p: any) => p.y);
    const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
    const sx = (v: number) => PL + ((v - x0) / ((x1 - x0) || 1)) * iw;
    const sy = (v: number) => PT + ih - ((v - y0) / ((y1 - y0) || 1)) * ih;
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Relationship scatter plot">
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={PL} x2={W - PR} y1={PT + ih * f} y2={PT + ih * f} stroke="currentColor" strokeOpacity={0.1} />
        ))}
        <line x1={sx(x0)} y1={sy(y0)} x2={sx(x1)} y2={sy(y1)} stroke="#4F46E5" strokeOpacity={0.35} strokeDasharray="4 4" />
        {pts.map((p: any, i: number) => (
          <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={4.5} fill="#4F46E5" fillOpacity={0.75}>
            <title>{`${p.l}: ${p.x.toLocaleString()} / ${p.y.toLocaleString()}`}</title>
          </circle>
        ))}
        <text x={PL} y={H - 6} fontSize={10} fill="currentColor" opacity={0.55}>{xs[0].toLocaleString()}</text>
        <text x={W - PR} y={H - 6} fontSize={10} fill="currentColor" opacity={0.55} textAnchor="end">{xs[xs.length - 1].toLocaleString()}</text>
      </svg>
    );
  }

  // Leaderboard: per-measure trend speed (%/period, diverging around zero)
  if (vtype === "leaderboard") {
    const rows = data.slice(0, 8).map((d: any) => ({ name: String(d.name ?? d.label ?? ""), value: Number(d.value ?? 0) })).filter((r: any) => !isNaN(r.value));
    if (!rows.length) return null;
    const maxPos = Math.max(0.1, ...rows.map((r: any) => Math.max(0, r.value)));
    const maxNeg = Math.max(0.1, ...rows.map((r: any) => Math.max(0, -r.value)));
    const zeroY = PT + ih * (maxPos / (maxPos + maxNeg));
    const rowH = ih / rows.length;
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Trend leaderboard chart">
        <line x1={PL} x2={W - PR} y1={zeroY} y2={zeroY} stroke="currentColor" strokeOpacity={0.3} />
        {rows.map((r: any, i: number) => {
          const yc = PT + i * rowH + rowH / 2;
          const half = (W - PL - PR - 110) / 2;
          const cx = PL + 110 + half;
          const w = Math.abs(r.value) / (r.value >= 0 ? maxPos : maxNeg) * half;
          const x = r.value >= 0 ? cx : cx - w;
          const pos = r.value >= 0;
          return (
            <g key={i}>
              <text x={PL} y={yc + 3.5} fontSize={10.5} textAnchor="start" fill="currentColor" opacity={0.75}>
                {(r.name.length > 18 ? r.name.slice(0, 17) + "…" : r.name)}
              </text>
              <rect x={x} y={yc - 8} width={Math.max(2, w)} height={16} rx={3} fill={pos ? "#059669" : "#DC2626"} opacity={i === 0 ? 1 : 0.7}>
                <title>{`${r.name}: ${r.value >= 0 ? "+" : ""}${r.value.toFixed(1)}% a period`}</title>
              </rect>
              <text x={pos ? x + Math.max(2, w) + 4 : x - 4} y={yc + 3.5} fontSize={10} fontWeight={700} textAnchor={pos ? "start" : "end"} fill={pos ? "#059669" : "#DC2626"}>
                {r.value >= 0 ? "+" : ""}{r.value.toFixed(1)}%
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  // Bar: opportunity / performance / segment payload {name, value}
  const isBarLike = vtype === "bar" || data[0]?.name !== undefined || cat === "opportunities" || cat === "performance";
  if (isBarLike) {
    const rows = data.slice(0, 8).map((d: any) => ({ name: String(d.name ?? d.period ?? d.label ?? ""), value: Number(d.value ?? d.val ?? 0) }));
    if (!rows.length || rows.every((r: any) => isNaN(r.value))) return null;
    const max = Math.max(...rows.map((r: any) => r.value), 1);
    const avg = rows.reduce((a: number, r: any) => a + r.value, 0) / rows.length;
    const bw = iw / rows.length;
    return (
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Breakdown bar chart">
        {[0.25, 0.5, 0.75, 1].map((f) => (
          <line key={f} x1={PL} x2={W - PR} y1={PT + ih * (1 - f)} y2={PT + ih * (1 - f)} stroke="currentColor" strokeOpacity={0.1} />
        ))}
        {/* average reference (inspo: dashed Average line) */}
        <line x1={PL} x2={W - PR} y1={PT + ih - (avg / max) * ih} y2={PT + ih - (avg / max) * ih} stroke="#64748B" strokeDasharray="5 4" strokeWidth={1.2} />
        <text x={W - PR} y={PT + ih - (avg / max) * ih - 4} fontSize={9.5} fill="#64748B" textAnchor="end">Avg {fmtMoney(avg)}</text>
        {rows.map((r: any, i: number) => {
          const h = Math.max(3, (r.value / max) * ih);
          const x = PL + i * bw + bw * 0.18;
          const top = i === 0;
          return (
            <g key={i}>
              <rect x={x} y={PT + ih - h} width={bw * 0.64} height={h} rx={3} fill={top ? "#4F46E5" : "#C7D2FE"} opacity={top ? 1 : 0.85}>
                <title>{`${r.name}: ${fmtMoney(r.value)}`}</title>
              </rect>
              <text x={x + bw * 0.32} y={PT + ih - h - 4} fontSize={9.5} fontWeight={700} textAnchor="middle" fill={top ? "#312E81" : "#64748B"}>
                {fmtMoney(r.value)}
              </text>
              <text x={x + bw * 0.32} y={H - 6} fontSize={9.5} textAnchor="middle" fill="currentColor" opacity={0.6}>
                {r.name.length > 12 ? r.name.slice(0, 11) + "…" : r.name}
              </text>
            </g>
          );
        })}
      </svg>
    );
  }

  // Line / area: time-series payload {period|label, value, anomaly?}
  const rows = data.map((d: any) => ({ label: String(d.period ?? d.label ?? ""), value: Number(d.value ?? d.val ?? 0), anomaly: Boolean(d.anomaly) }));
  if (rows.length < 2 || rows.every((r: any) => isNaN(r.value))) return null;
  const vals = rows.map((r: any) => r.value);
  const max = Math.max(...vals), min = Math.min(...vals);
  const span = (max - min) || 1;
  const X = (i: number) => PL + (i / (rows.length - 1)) * iw;
  const Y = (v: number) => PT + ih - ((v - min) / span) * ih;
  const line = rows.map((r: any, i: number) => `${X(i)},${Y(r.value)}`).join(" ");
  const area = `${PL},${PT + ih} ${line} ${X(rows.length - 1)},${PT + ih}`;
  const anoms = rows.map((r: any, i: number) => ({ ...r, i })).filter((r: any) => r.anomaly);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Trend line chart">
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <line key={f} x1={PL} x2={W - PR} y1={PT + ih * (1 - f)} y2={PT + ih * (1 - f)} stroke="currentColor" strokeOpacity={0.1} />
      ))}
      <polygon points={area} fill="#4F46E5" opacity={0.08} />
      <polyline points={line} fill="none" stroke="#4F46E5" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      {rows.map((r: any, i: number) => (
        <circle key={i} cx={X(i)} cy={Y(r.value)} r={r.anomaly ? 5 : 3} fill={r.anomaly ? "#DC2626" : "#4F46E5"} stroke="#fff" strokeWidth={1.5}>
          <title>{`${r.label}: ${fmtMoney(r.value)}${r.anomaly ? " (unusual)" : ""}`}</title>
        </circle>
      ))}
      {anoms.length > 0 && (
        <text x={X(anoms[0].i)} y={Math.max(10, Y(anoms[0].value) - 10)} fontSize={10} fontWeight={700} fill="#DC2626" textAnchor="middle">unusual</text>
      )}
      <text x={PL} y={H - 6} fontSize={10} fill="currentColor" opacity={0.55}>{rows[0].label.slice(0, 7)}</text>
      <text x={(PL + W - PR) / 2} y={H - 6} fontSize={10} fill="currentColor" opacity={0.55} textAnchor="middle">
        {rows.length > 2 ? rows[Math.floor(rows.length / 2)].label.slice(0, 7) : ""}
      </text>
      <text x={W - PR} y={H - 6} fontSize={10} fill="currentColor" opacity={0.55} textAnchor="end">{rows[rows.length - 1].label.slice(0, 7)}</text>
    </svg>
  );
}

/* ============================ Left feed card ============================ */
function FeedCard({ ins, selected, onSelect }: { ins: Insight; selected: boolean; onSelect: () => void }) {
  const conf = confidenceInfo(ins.confidence);
  const accent = severityAccent(ins.severity);
  const change = ins.evidence?.changePercent;
  const changeTone = change === null || change === undefined ? "text-muted-foreground" : change >= 0 ? "text-positive" : "text-negative";
  return (
    <button
      onClick={onSelect}
      className={`w-full text-left bg-card border rounded-xl px-3.5 py-3 transition-all animate-fade-in-scale ${selected ? "border-primary shadow-md" : "border-border hover:border-primary/40 hover:shadow-sm"}`}
      style={{ borderLeft: `3px solid ${accent}` }}
      aria-expanded={selected}
    >
      <div className="flex items-center gap-1.5 text-[10px] font-semibold tracking-wide">
        <span className="text-primary">{typeLabel(ins.type)}</span>
        <span className="text-muted-foreground font-normal">· {(ins.severity || "low").toLowerCase()}</span>
        <span className="ml-auto text-muted-foreground font-normal">{ins.affectedPeriod ? ins.affectedPeriod.split(" to ").pop() : "Today"}</span>
      </div>
      <p className="mt-1 text-[13px] font-semibold text-foreground leading-snug line-clamp-2">{ins.title}</p>
      <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed line-clamp-2">“{ins.description}”</p>
      <div className="mt-2 flex items-center gap-2 flex-wrap">
        {ins.magnitude && (
          <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded bg-secondary ${changeTone}`}>{ins.magnitude}</span>
        )}
        <span className={`text-[10px] font-medium ${conf.tone}`}>{typeof ins.confidence === "number" ? `${conf.label} · ${ins.confidence}%` : conf.label}</span>
      </div>
      {ins.recommendedNextAnalysis?.question && (
        <p className="mt-1.5 text-[11px] text-muted-foreground leading-snug">
          <span className="text-primary font-medium">Recommended:</span> <span className="line-clamp-1">{ins.recommendedNextAnalysis.question}</span>
        </p>
      )}
      <span className="mt-2 inline-flex items-center gap-1 text-[11px] font-medium text-primary">
        {selected ? "Viewing evidence" : "Expand Insight"} <ChevronRight size={12} />
      </span>
    </button>
  );
}

/* ============================ Main page ============================ */
export default function Insights({
  insightResult = null,
  insightStatus = "idle",
  insightError = "",
  connectionStatus = "not-connected",
  onAskQuestion,
}: {
  insightResult?: any;
  insightStatus?: string;
  insightError?: string;
  connectionStatus?: string;
  onAskQuestion?: (question: string) => void;
}) {
  const theme = useTheme() as any;
  const setPage = theme?.setPage;
  const [activeFilter, setActiveFilter] = useState<string>("all");
  const [criticalOnly, setCriticalOnly] = useState<boolean>(false);
  const [metricFilter, setMetricFilter] = useState<string>("All");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [savedIds, setSavedIds] = useState<string[]>([]);
  const [insights, setInsights] = useState<Insight[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [fetchedAt, setFetchedAt] = useState<string>("");

  const fetchInsights = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch(`/api/insights`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (data.ok && data.insights) {
        setInsights(data.insights);
        setFetchedAt(new Date().toISOString());
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
      const res = await fetch(`/api/insights/saved`, { headers: { Authorization: `Bearer ${token}` } });
      const data = await res.json();
      if (data.ok && data.saved) setSavedIds(data.saved.map((s: any) => s.insight_id));
    } catch { /* non-fatal */ }
  }, []);

  useEffect(() => {
    if (connectionStatus === "connected") fetchInsights();
    fetchSaved();
  }, [connectionStatus, fetchInsights, fetchSaved]);

  const propInsights: Insight[] = insightResult?.keyInsights || [];
  const allInsights: Insight[] = insights.length > 0 ? insights : propInsights;

  const metrics = useMemo(() => ["All", ...Array.from(new Set(allInsights.map((i) => (i.metric || "").split(" (")[0]).filter(Boolean))).slice(0, 12)], [allInsights]);

  const filtered = useMemo(() => allInsights.filter((ins) => {
    const catOk = matchesFilter(ins.type, activeFilter);
    const critOk = !criticalOnly || (ins.severity || "").toLowerCase() === "high";
    const metricOk = metricFilter === "All" || (ins.metric || "").startsWith(metricFilter) || (ins.metric || "") === metricFilter;
    return catOk && critOk && metricOk;
  }), [allInsights, activeFilter, criticalOnly, metricFilter]);

  useEffect(() => {
    if (!selectedId && filtered.length > 0) setSelectedId(filtered[0].id);
    if (selectedId && !filtered.some((i) => i.id === selectedId) && filtered.length > 0) setSelectedId(filtered[0].id);
  }, [filtered, selectedId]);

  const selected: Insight | null = filtered.find((i) => i.id === selectedId) || filtered[0] || null;

  const counts = useMemo(() => {
    const c: Record<string, number> = { critical: 0 };
    for (const f of FILTERS) {
      if (f.id === "all") continue;
      c[f.id] = allInsights.filter((ins) => matchesFilter(ins.type, f.id)).length;
    }
    for (const ins of allInsights) {
      if ((ins.severity || "").toLowerCase() === "high") c.critical += 1;
    }
    return c;
  }, [allInsights]);

  /* ---- Real module handoff (§14): never dummy. Persist structured context
     so Hypothesis / Forecast / Prescription open with it, primary path goes
     through Copilot (page isolation rule) or direct setPage navigation. ---- */
  const handoffContext = (ins: Insight) => ({
    insight_id: ins.id,
    insight_type: ins.type,
    title: ins.title,
    description: ins.description,
    metric: ins.metric,
    magnitude: ins.magnitude,
    confidence: ins.confidence,
    affected_period: ins.affectedPeriod,
    dimensions: ins.recommendedNextAnalysis?.dimensions || [],
    question: ins.recommendedNextAnalysis?.question || ins.description,
    source: ins.source || { tables: [], columns: [] },
  });

  const persistHandoff = (ins: Insight) => {
    try {
      sessionStorage.setItem("aria_insight_handoff", JSON.stringify(handoffContext(ins)));
    } catch { /* storage full: navigation still works */ }
  };

  const askCopilot = async (ins: Insight, question: string) => {
    persistHandoff(ins);
    try {
      const token = localStorage.getItem("aria_auth_token");
      await fetch(`/api/insights/${ins.id}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question, insight_id: ins.id }),
      });
    } catch { /* backend trace is best-effort; Copilot still runs */ }
    if (onAskQuestion) onAskQuestion(question);
  };

  const openHypothesis = (ins: Insight) => {
    persistHandoff(ins);
    const dims = ins.recommendedNextAnalysis?.dimensions || [];
    const q = ins.recommendedNextAnalysis?.question || `Why did ${ins.metric} change (${ins.magnitude})?`;
    try {
      sessionStorage.setItem("aria_hypothesis_prefill", JSON.stringify({
        metric: ins.metric, driver: dims[0] || "", segment: dims[1] || "",
        period: ins.affectedPeriod, question: q, source: ins.source,
      }));
    } catch { /* ignore */ }
    if (setPage) setPage("hypothesis");
    else askCopilot(ins, `Test this hypothesis: ${q}`);
  };

  const openForecast = (ins: Insight) => {
    persistHandoff(ins);
    try {
      sessionStorage.setItem("aria_forecast_prefill", JSON.stringify({ metric: ins.metric, period: ins.affectedPeriod, source: ins.source }));
    } catch { /* ignore */ }
    if (setPage) setPage("predictive");
    else askCopilot(ins, `Forecast ${ins.metric} over the next periods given: ${ins.description}`);
  };

  const openPrescription = (ins: Insight) => {
    persistHandoff(ins);
    if (setPage) setPage("prescription");
    else askCopilot(ins, `What should we do about: ${ins.title}? ${ins.description}`);
  };

  const toggleSave = async (ins: Insight) => {
    const isSaved = savedIds.includes(ins.id);
    const token = localStorage.getItem("aria_auth_token");
    try {
      if (isSaved) {
        await fetch(`/api/insights/save/${ins.id}`, { method: "DELETE", headers: { Authorization: `Bearer ${token}` } });
        setSavedIds((s) => s.filter((id) => id !== ins.id));
      } else {
        await fetch(`/api/insights/save`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ insight_id: ins.id, title: ins.title, insight_type: ins.type, severity: ins.severity, metric: ins.metric, insight_payload: ins }),
        });
        setSavedIds((s) => [...s, ins.id]);
      }
    } catch { /* non-fatal */ }
  };

  const handleShare = async (ins: Insight) => {
    const text = `${ins.title}\n\n${ins.description}\n\nMetric: ${ins.metric}\nConfidence: ${ins.confidence}%`;
    try {
      if (navigator.share) await navigator.share({ title: ins.title, text });
      else await navigator.clipboard.writeText(text);
    } catch { /* dismissed */ }
  };

  /* ------------------------- Failure / empty states ------------------------- */
  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <h2 className="text-xl font-semibold text-foreground tracking-tight">Insights</h2>
        <p className="text-sm text-muted-foreground mt-0.5">ARIA automatically found meaningful patterns in your connected data.</p>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <Database size={22} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">No data source connected</p>
          <p className="text-xs text-muted-foreground mt-1">Connect PostgreSQL, MySQL, or upload a CSV to let ARIA investigate your data.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="text-center py-12">
          <Loader2 size={24} className="animate-spin text-primary mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">Analyzing time-series data…</p>
          <p className="text-xs text-muted-foreground mt-1">Profiling columns · selecting analyses · validating evidence</p>
        </div>
      </div>
    );
  }

  if ((error || insightError) && !allInsights.length) {
    const msg = error || insightError;
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <h2 className="text-xl font-semibold text-foreground tracking-tight">Insights</h2>
        <p className="text-sm text-muted-foreground mt-0.5">ARIA automatically found meaningful patterns in your connected data.</p>
        <div className="mt-6 bg-card border border-border rounded-xl p-5 flex gap-3">
          <AlertTriangle size={18} className="text-warning flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm text-foreground font-medium">ARIA couldn't generate insights for this dataset</p>
            <p className="text-xs text-muted-foreground mt-1">{msg}</p>
            <p className="text-xs text-muted-foreground mt-1">ARIA needs a measurable metric with enough historical observations. Check for empty tables, missing date fields, or excessive nulls.</p>
            <button onClick={fetchInsights} className="mt-2 text-xs text-primary hover:underline">Try again</button>
          </div>
        </div>
      </div>
    );
  }

  if (!allInsights.length) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-semibold text-foreground tracking-tight">Insights</h2>
            <p className="text-sm text-muted-foreground mt-0.5">ARIA automatically found meaningful patterns in your connected data.</p>
          </div>
          <button onClick={fetchInsights} className="p-2 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors" title="Refresh Analysis">
            <RefreshCw size={14} />
          </button>
        </div>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <Sparkles size={22} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">No strong patterns yet</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">ARIA investigated the connected data but found nothing stable enough to report. Weak evidence is never promoted into a business claim.</p>
        </div>
      </div>
    );
  }

  /* --------------------------------- Workspace --------------------------------- */
  const selChange = selected?.evidence?.changePercent;
  const impact = selected?.businessImpact;
  const showMoneyDisclaimer = !impact?.explanation || impact.value === 0 || impact.value === null || impact.value === undefined || impact.direction === "neutral";

  return (
    <div className="p-4 md:p-6 max-w-[1400px] mx-auto space-y-4">
      {/* Header (§7): compact premium, source + last analyzed + refresh */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Insights</h2>
          <p className="text-[13px] text-muted-foreground mt-0.5">ARIA automatically found meaningful patterns in your connected data.</p>
          <div className="mt-1.5 flex items-center gap-3 text-[11px] text-muted-foreground flex-wrap">
            <span className="inline-flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-positive inline-block" />{selected?.source?.tables?.[0] || "Connected source"}</span>
            {fetchedAt && <span className="inline-flex items-center gap-1"><Clock size={11} />Last analyzed {new Date(fetchedAt).toLocaleTimeString()}</span>}
          </div>
        </div>
        <button onClick={fetchInsights} className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-2 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors">
          <RefreshCw size={13} /> Refresh Analysis
        </button>
      </div>

      {/* Summary + filters (§8/§9): one compact strip — count, every type
          filter with live counts, Critical severity, metric dropdown */}
      <div className="bg-card border border-border rounded-xl px-4 py-3 flex items-center gap-2 flex-wrap">
        <p className="text-[13px] text-foreground mr-1"><span className="font-semibold">ARIA found {allInsights.length} meaningful insight{allInsights.length === 1 ? "" : "s"}.</span></p>
        {FILTERS.map((f) => (
          <button key={f.id} onClick={() => setActiveFilter(f.id)}
            className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${activeFilter === f.id ? "bg-primary text-primary-foreground border-primary" : "bg-card text-muted-foreground border-border hover:text-foreground"}`}>
            {f.label}{f.id !== "all" ? ` · ${counts[f.id] ?? 0}` : ""}
          </button>
        ))}
        <button onClick={() => setCriticalOnly((v) => !v)} className={`text-[11px] px-2.5 py-1 rounded-full border transition-colors ${criticalOnly ? "bg-negative text-white border-negative" : "border-border text-muted-foreground hover:text-foreground"}`}>Critical · {counts.critical}</button>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[11px] text-muted-foreground">{filtered.length} of {allInsights.length}</span>
          <Filter size={12} className="text-muted-foreground" />
          <select value={metricFilter} onChange={(e) => setMetricFilter(e.target.value)} className="text-[11px] bg-secondary border border-border rounded-lg px-2 py-1.5 text-foreground max-w-[180px]" aria-label="Filter by metric">
            {metrics.map((m) => <option key={m} value={m}>{m === "All" ? "All metrics" : m}</option>)}
          </select>
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="text-center py-14 bg-card border border-border rounded-xl">
          <Filter size={20} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">No insights match these filters</p>
          <button onClick={() => { setActiveFilter("all"); setMetricFilter("All"); setCriticalOnly(false); }} className="mt-2 text-xs text-primary hover:underline">Clear filters</button>
        </div>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-[370px_minmax(0,1fr)] gap-4 items-start">
          {/* Left: vertical investigation feed (§2 collapsed state, inspo 1) */}
          <div className="space-y-2.5 max-h-[calc(100vh-280px)] lg:overflow-y-auto lg:pr-1 premium-scroll">
            {filtered.map((ins) => (
              <FeedCard key={ins.id} ins={ins} selected={selected?.id === ins.id} onSelect={() => setSelectedId(ins.id)} />
            ))}
          </div>

          {/* Right: evidence workspace (§3 expanded state) */}
          {selected && (
            <article key={selected.id} className="bg-card border border-border rounded-xl overflow-hidden animate-fade-in">
              <div className="px-5 pt-4 pb-3 border-b border-border">
                <div className="flex items-center gap-2 text-[10px] font-semibold tracking-wider flex-wrap">
                  <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">{typeLabel(selected.type)}</span>
                  <span className="px-2 py-0.5 rounded-full border border-border text-muted-foreground capitalize">{selected.severity} priority</span>
                  <span className="ml-auto"><ConfidenceDots conf={selected.confidence} /></span>
                </div>
                <h3 className="mt-2 text-[17px] font-semibold text-foreground leading-snug">{selected.title}</h3>
                <p className="mt-1 text-[13px] text-muted-foreground leading-relaxed">“{selected.description}”</p>
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  {selected.magnitude && (
                    <span className={`text-xs font-bold px-2 py-1 rounded-md ${selChange === null || selChange === undefined ? "bg-secondary text-foreground" : selChange >= 0 ? "bg-positive/10 text-positive" : "bg-negative/10 text-negative"}`}>
                      {selected.magnitude}
                    </span>
                  )}
                  {selected.affectedPeriod && <span className="text-[11px] text-muted-foreground">{selected.affectedPeriod}</span>}
                  <span className="ml-auto flex items-center gap-1">
                    <button onClick={() => toggleSave(selected)} className={`p-1.5 rounded-lg transition-colors ${savedIds.includes(selected.id) ? "text-primary" : "text-muted-foreground hover:text-foreground"} hover:bg-secondary`} title="Save insight">
                      <Bookmark size={14} fill={savedIds.includes(selected.id) ? "currentColor" : "none"} />
                    </button>
                    <button onClick={() => handleShare(selected)} className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors" title="Share">
                      <Share2 size={14} />
                    </button>
                  </span>
                </div>
              </div>

              <div className="px-5 py-4 space-y-4">
                {/* 1. OBSERVATION */}
                <section>
                  <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.08em]">Observation</p>
                  <div className="mt-1.5 text-[13px] text-foreground leading-relaxed space-y-1">
                    {(selected.evidence?.observations?.length ? selected.evidence.observations : [selected.description]).slice(0, 4).map((o, i) => (
                      <p key={i}>{o}</p>
                    ))}
                  </div>
                </section>

                {/* 2. EVIDENCE */}
                <section className="border-t border-border pt-4">
                  <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.08em]">Evidence</p>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">Here is the proof behind ARIA's observation.</p>
                  <div className="mt-2 rounded-lg border border-border bg-background/60 p-3 text-foreground">
                    <EvidenceChart ins={selected} />
                    {(!selected.visualization?.data?.length) && (
                      <p className="text-xs text-muted-foreground">Chart unavailable for this insight — supporting values below still describe the evidence.</p>
                    )}
                  </div>
                  <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
                    {selected.evidence?.currentValue !== null && selected.evidence?.currentValue !== undefined && (
                      <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Current</p><p className="font-semibold text-foreground">{fmtMoney(selected.evidence.currentValue)}</p></div>
                    )}
                    {selected.evidence?.baseline !== null && selected.evidence?.baseline !== undefined && (
                      <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Baseline</p><p className="font-semibold text-foreground">{fmtMoney(selected.evidence.baseline)}</p></div>
                    )}
                    {selected.evidence?.sampleSize !== null && selected.evidence?.sampleSize !== undefined && (
                      <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Sample</p><p className="font-semibold text-foreground">{selected.evidence.sampleSize} periods</p></div>
                    )}
                    <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Strength</p><p className="font-semibold text-foreground">{typeof selected.confidence === "number" ? `${selected.confidence}%` : "—"}</p></div>
                  </div>
                  {!!selected.evidence?.supportingMetrics?.length && (
                    <ul className="mt-2 space-y-1">
                      {selected.evidence.supportingMetrics.slice(0, 4).map((m, i) => (
                        <li key={i} className="text-xs text-foreground"><span className="text-muted-foreground">• </span>{m}</li>
                      ))}
                    </ul>
                  )}
                </section>

                {/* 3. BUSINESS IMPACT */}
                <section className="border-t border-border pt-4">
                  <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.08em]">Business Impact</p>
                  <p className="mt-1.5 text-[13px] text-foreground leading-relaxed">
                    {impact?.explanation || "The available data does not contain enough information to estimate its financial impact."}
                  </p>
                  {!showMoneyDisclaimer && impact?.value !== undefined && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Estimated impact: <span className={`font-semibold ${impact.direction === "positive" ? "text-positive" : impact.direction === "negative" ? "text-negative" : "text-foreground"}`}>{fmtMoney(Math.abs(impact.value))}</span>
                    </p>
                  )}
                  {showMoneyDisclaimer && impact?.explanation && (
                    <p className="mt-1 text-[11px] text-muted-foreground">Impact could not be reliably estimated from the available data — no monetary value is invented.</p>
                  )}
                </section>

                {/* 4. RECOMMENDED NEXT ANALYSIS */}
                <section className="border-t border-border pt-4">
                  <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-[0.08em]">Recommended Next Analysis</p>
                  <div className="mt-2 rounded-lg border border-primary/25 bg-primary/5 p-3">
                    <p className="text-[13px] font-medium text-foreground leading-snug">
                      {selected.recommendedNextAnalysis?.question || "Ask ARIA to investigate the main driver behind this finding."}
                    </p>
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      <button onClick={() => openHypothesis(selected)} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity">
                        <FlaskConical size={12} /> Test Hypothesis
                      </button>
                      <button onClick={() => openForecast(selected)} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors">
                        <TrendingUp size={12} /> Forecast Impact
                      </button>
                      <button onClick={() => openPrescription(selected)} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors">
                        <ClipboardList size={12} /> Create Prescription
                      </button>
                      <button onClick={() => askCopilot(selected, selected.recommendedNextAnalysis?.question || selected.description)} className="inline-flex items-center gap-1 text-[11px] font-medium px-2.5 py-1.5 rounded-lg border border-border bg-card text-foreground hover:border-primary/50 transition-colors">
                        <MessageSquare size={12} /> Ask ARIA
                      </button>
                    </div>
                  </div>
                  {selected.source && (
                    <p className="mt-2 text-[10px] text-muted-foreground">Evidence from: {(selected.source.tables || []).join(", ") || "connected data"}{selected.source.columns?.length ? ` · ${(selected.source.columns || []).slice(0, 4).join(", ")}` : ""}</p>
                  )}
                </section>

                {/* Prev / Next (one expanded at a time, §10) */}
                <div className="flex items-center justify-between pt-1">
                  <button
                    onClick={() => { const i = filtered.findIndex((x) => x.id === selected.id); if (i > 0) setSelectedId(filtered[i - 1].id); }}
                    disabled={filtered.findIndex((x) => x.id === selected.id) <= 0}
                    className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 inline-flex items-center gap-1">
                    ← Previous finding
                  </button>
                  <button
                    onClick={() => askCopilot(selected, `What is driving ${selected.metric}? Break down ${selected.magnitude} by the top contributing dimensions in ${selected.affectedPeriod}.`)}
                    className="text-[11px] text-primary hover:underline inline-flex items-center gap-1">
                    See What's Driving This <ChevronDown size={12} />
                  </button>
                  <button
                    onClick={() => { const i = filtered.findIndex((x) => x.id === selected.id); if (i < filtered.length - 1) setSelectedId(filtered[i + 1].id); }}
                    disabled={filtered.findIndex((x) => x.id === selected.id) >= filtered.length - 1}
                    className="text-[11px] text-muted-foreground hover:text-foreground disabled:opacity-40 inline-flex items-center gap-1">
                    Next finding →
                  </button>
                </div>
              </div>
            </article>
          )}
        </div>
      )}
    </div>
  );
}
