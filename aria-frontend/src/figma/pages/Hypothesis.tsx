import { useState, useEffect, useMemo, useRef } from "react";
import { Loader2, CheckCircle, XCircle, ArrowRight, Save, Trash2, Beaker, AlertTriangle, ChevronDown, ChevronUp, Sparkles, Database, ListChecks } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, BarChart, Bar, Cell } from "recharts";
import { useTheme } from "../App";
import Evidence from "../components/Evidence";
import { confidenceWord } from "../lib/format";

/* =====================================================================
   ARIA Hypothesis — evidence-based assumption testing (t.txt §§1–83).
   LLM understands/explains; deterministic engine tests. States (§73):
   NO_SOURCE READY PARSING PREVIEW CLARIFY ANALYZING COMPLETED
   NOT_TESTABLE NEEDS_MORE_DATA FAILED. A failed analysis is a verdict
   card, never a broken page (§72).
   ===================================================================== */

type HypStatus = "idle" | "parsing" | "preview" | "clarify" | "running" | "done" | "error";

const FALLBACK_IDEAS = [
  "Do higher values of one number relate to another?",
  "Does the main number differ across categories?",
  "Has the main number changed over time?",
  "Are weekend values higher?",
];

const LOAD_STAGES = [
  "Understanding hypothesis…",
  "Checking available data…",
  "Validating variables…",
  "Selecting analytical method…",
  "Testing evidence…",
  "Checking robustness…",
  "Building visualization…",
  "Generating explanation…",
];

/* ---- Centralized error map (§50): one place, never per-component ---- */
const ERROR_MAP: Record<string, { title: string; hint: string }> = {
  NO_CONNECTION: { title: "No data source connected", hint: "Connect PostgreSQL, MySQL, or upload a CSV to test hypotheses against real data." },
  INVALID_SOURCE: { title: "Couldn't read this source", hint: "Reconnect your data source, then try again." },
  PARSING_FAILED: { title: "ARIA couldn't parse that", hint: "Phrase it as a testable question, e.g. does price affect sales?" },
  COLUMN_NOT_FOUND: { title: "This hypothesis can't be tested with the current data", hint: "ARIA couldn't identify a suitable field. Pick from the available fields or try another hypothesis." },
  AMBIGUOUS_COLUMN: { title: "ARIA needs a little clarification", hint: "Choose which fields to test — ARIA won't guess when confidence is low." },
  INCOMPATIBLE_DATA_TYPE: { title: "These fields aren't compatible with this analysis", hint: "Relationship tests need numbers; group tests need a category. Try different fields." },
  INSUFFICIENT_DATA: { title: "This hypothesis needs more reliable observations", hint: "ARIA cannot produce a reliable result from this sample." },
  INSUFFICIENT_HISTORY: { title: "Not enough history for this test", hint: "Time-based tests need a longer dated series." },
  INVALID_GROUPING: { title: "The groups can't be compared", hint: "Each group needs enough observations. Try a dimension with fewer, larger groups." },
  INVALID_DATE_RANGE: { title: "The date range doesn't support this test", hint: "Before/after tests need observations on both sides of the split." },
  UNSUPPORTED_ANALYSIS: { title: "ARIA can't run that analysis yet", hint: "Try a relationship, group comparison, or trend question." },
  ANALYSIS_FAILED: { title: "The analysis could not be completed", hint: "Your data was not changed. Try again or rephrase the question." },
  STATISTICAL_TEST_FAILED: { title: "The statistical test failed", hint: "The data didn't meet the test's requirements. Try a different framing." },
  CHART_FAILED: { title: "Visualization unavailable", hint: "The verdict and numbers below are still valid." },
  LLM_FAILED: { title: "Explanation unavailable", hint: "The analysis completed — only ARIA's wording service is down. The statistical evidence still stands." },
  TIMEOUT: { title: "The analysis timed out", hint: "Try a narrower question or reconnect, then run again." },
  INTERNAL_ERROR: { title: "Something went wrong", hint: "Your data was not changed. Try again." },
};

interface Props {
  insightResult?: any;
  onAskQuestion?: (question: string) => void;
  connectionStatus?: string;
}

const SAVED_KEY = "aria_saved_hypotheses";

export default function Hypothesis({ insightResult, onAskQuestion, connectionStatus = "not-connected" }: Props) {
  const { isDark, setPage } = useTheme() as any;
  const [question, setQuestion] = useState("");
  const [hypText, setHypText] = useState("");
  const [hypEdited, setHypEdited] = useState(false);
  const [status, setStatus] = useState<HypStatus>("idle");
  const [stage, setStage] = useState(0);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [ideas, setIdeas] = useState<string[]>(FALLBACK_IDEAS);
  const [ideaCards, setIdeaCards] = useState<any[]>([]);
  const [openIdea, setOpenIdea] = useState<number | null>(0);
  const [dbName, setDbName] = useState("Connected Data");
  const [segDim, setSegDim] = useState(0);
  const [simPct, setSimPct] = useState(10);
  const [saved, setSaved] = useState<any[]>([]);
  // Preview (§33) + ambiguity (§62) + context (§47)
  const [preview, setPreview] = useState<any>(null);
  const [clarify, setClarify] = useState<any>(null);
  const [pickedMetric, setPickedMetric] = useState<string>("");
  const [pickedDriver, setPickedDriver] = useState<string>("");
  const [availFields, setAvailFields] = useState<any[]>([]);
  const [prep, setPrep] = useState<any>(null);
  const prefillDone = useRef(false);

  const authHeader = () => {
    const token = localStorage.getItem("aria_auth_token");
    return { Authorization: `Bearer ${token}` };
  };

  useEffect(() => {
    try {
      setSaved(JSON.parse(localStorage.getItem(SAVED_KEY) || "[]"));
    } catch { setSaved([]); }
    const token = localStorage.getItem("aria_auth_token");
    if (token) {
      fetch("/api/session/status", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => { if (d.db_name) setDbName(d.db_name); })
        .catch(() => {});
      fetch("/api/hypothesis/suggest", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => {
          if (d.ok && Array.isArray(d.suggestions) && d.suggestions.length) setIdeas(d.suggestions);
          if (d.ok && Array.isArray(d.cards) && d.cards.length) setIdeaCards(d.cards);
        })
        .catch(() => {});
    }
    // Cross-module handoff (§42): Insights "Test Hypothesis" lands here
    // with metric/driver/segment/period already populated.
    if (!prefillDone.current) {
      prefillDone.current = true;
      try {
        const raw = sessionStorage.getItem("aria_hypothesis_prefill");
        if (raw) {
          const h = JSON.parse(raw);
          sessionStorage.removeItem("aria_hypothesis_prefill");
          const q = h.question || (h.metric ? `Does ${h.driver || "the main driver"} affect ${h.metric}?` : "");
          if (q) {
            setQuestion(q);
            if (h.metric) setPickedMetric(h.metric);
            if (h.driver) setPickedDriver(h.driver);
            setTimeout(() => parseHypothesis(q, h.metric || "", h.driver || ""), 350);
          }
        }
      } catch { /* prefill is best-effort */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  /* ---- Parse (§12): preview first, never straight to statistics ---- */
  const parseHypothesis = async (q?: string, metric = "", driver = "") => {
    const text = (q ?? question).trim();
    if (!text) return;
    setQuestion(text);
    setStatus("parsing");
    setError(""); setErrorCode("");
    setResult(null); setPreview(null); setClarify(null);
    try {
      const res = await fetch("/api/hypotheses/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ question: text, metric: metric || undefined, driver: driver || undefined }),
      });
      const data = await res.json();
      if (data.ok && data.preview) {
        setPreview(data.preview);
        setPickedMetric(data.preview.metric || "");
        setPickedDriver(data.preview.driver || "");
        setPrep({ rows_available: data.preview.rows_available, usable: data.preview.usable_observations });
        setStatus("preview");
        return;
      }
      if (data.code === "AMBIGUOUS_COLUMN" && data.options) {
        setClarify({ message: data.detail, options: data.options, hypothesis: data.hypothesis });
        if (data.options.metrics?.length === 1) setPickedMetric(data.options.metrics[0].column);
        setStatus("clarify");
        return;
      }
      failWith(data);
    } catch (err: any) {
      failWith({ code: "ANALYSIS_FAILED", detail: err?.message });
    }
  };

  const failWith = (data: any) => {
    const code = data?.code || "ANALYSIS_FAILED";
    // Analytical outcomes, not crashes (§72): route verdicts to states.
    if (data?.verdict === "NEEDS MORE DATA" || code === "INSUFFICIENT_DATA") {
      setResult({ needMore: true, detail: data.detail, hypothesis: data.hypothesis, code });
      setErrorCode(code);
      setStatus("done");
      return;
    }
    if (data?.verdict === "NOT TESTABLE" || code === "COLUMN_NOT_FOUND") {
      setErrorCode(code);
      setError(data.detail || "");
      loadAvailFields();
      setStatus("done");
      setResult({ notTestable: true, detail: data.detail, hypothesis: data.hypothesis, code, options: data.options });
      return;
    }
    setErrorCode(code);
    setError(data?.detail || data?.message || "The analysis could not run.");
    setStatus("error");
  };

  const loadAvailFields = async () => {
    try {
      const res = await fetch("/api/hypotheses/context", { headers: authHeader() });
      const data = await res.json();
      if (data.ok) setAvailFields([...(data.metrics || []), ...(data.dimensions || []).slice(0, 8)]);
    } catch { /* optional panel */ }
  };

  /* ---- Run (§20–§29): statistics already validated by preview ---- */
  const analyze = async (q?: string) => {
    const text = (q ?? (hypEdited ? hypText : question)).trim();
    if (!text) return;
    setQuestion(text);
    setStatus("running");
    setStage(0);
    setError(""); setErrorCode("");
    setResult(null);
    const timer = setInterval(() => setStage((s) => Math.min(s + 1, LOAD_STAGES.length - 1)), 1400);
    try {
      const res = await fetch("/api/hypothesis/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ question: text, metric: pickedMetric || undefined, driver: pickedDriver || undefined }),
      });
      const data = await res.json();
      clearInterval(timer);
      if (data.ok === false) {
        failWith(data);
        return;
      }
      setHypText(data.hypothesis || "");
      setHypEdited(false);
      setSegDim(0);
      setSimPct(10);
      setPrep((p: any) => p || { usable: data.result?.n });
      setResult(data);
      setStatus("done");
    } catch (err: any) {
      clearInterval(timer);
      setErrorCode("ANALYSIS_FAILED");
      setError(err?.message || "The analysis could not run. Check your connection and try again.");
      setStatus("error");
    }
  };

  const saveCurrent = () => {
    if (!result || result.needMore || result.notTestable) return;
    const entry = {
      id: Date.now(), question, hypothesis: hypText || result.hypothesis,
      verdict: result.verdict, analysis: result.result?.analysis,
      metric: result.intent?.metric, driver: result.intent?.driver,
      ts: new Date().toISOString(), db: dbName,
    };
    const next = [entry, ...saved].slice(0, 20);
    setSaved(next);
    try { localStorage.setItem(SAVED_KEY, JSON.stringify(next)); } catch {}
  };

  const r = result?.result || null;
  const verdict = result?.verdict || null;
  const needMore = !!result?.needMore;
  const notTestable = !!result?.notTestable;
  const significant = verdict === "SUPPORTED";
  const segments: any[] = result?.segments || [];
  const activeSeg = segments[Math.min(segDim, Math.max(0, segments.length - 1))] || null;
  const whatif = result?.whatif || null;
  const showWhatIf = !!r && !!whatif && (r.analysis === "correlation");

  const simOutcome = useMemo(() => {
    if (!showWhatIf || !r) return null;
    const base = Number(r.metric_mean);
    const delta = Number(r.slope) * Number(r.driver_mean) * (simPct / 100);
    return { base, scenario: base + delta, delta };
  }, [showWhatIf, r, simPct]);

  const viz = r?.viz || null;
  const trendLine = useMemo(() => {
    if (!viz || viz.type !== "scatter" || r?.slope === undefined) return null;
    const pts: any[] = viz.points || [];
    if (pts.length < 2) return null;
    const xs = pts.map((p: any) => Number(p.x)).filter((v: number) => !isNaN(v));
    if (!xs.length) return null;
    const lo = Math.min(...xs), hi = Math.max(...xs);
    return [{ x: lo, y: r.slope * lo + Number(r.intercept || 0) }, { x: hi, y: r.slope * hi + Number(r.intercept || 0) }];
  }, [viz, r]);

  const barData = useMemo(() => {
    if (!viz) return [];
    if (viz.type === "bar" || viz.type === "comparison") return viz.groups || [];
    if (viz.type === "grouped") return (viz.groups || []).map((g: any) => ({ label: g.label, value: g.value }));
    return [];
  }, [viz]);

  const lineData = useMemo(() => {
    if (!viz || viz.type !== "line") return [];
    return viz.points || [];
  }, [viz]);

  const dqChecks = useMemo(() => {
    if (!r) return [];
    return [
      { label: "Records studied", sub: `${Number(r.n || 0).toLocaleString()} rows (min 10)`, done: Number(r.n || 0) >= 10 },
      { label: "Tested pair", sub: `${r.driver} → ${r.metric}`, done: true },
      { label: "Method", sub: r.analysis === "correlation" ? "Pearson + Spearman" : r.analysis === "trend" ? "Trend regression" : r.analysis === "segment" ? "Kruskal-Wallis + group means" : "Welch t + Mann-Whitney", done: true },
      { label: "Significance", sub: `p = ${Number(r.p_value) < 0.001 ? "<0.001" : Number(r.p_value).toFixed(3)}`, done: Number(r.p_value) < 0.05 },
    ];
  }, [r]);

  const errInfo = ERROR_MAP[errorCode] || ERROR_MAP.ANALYSIS_FAILED;

  /* ---- NO_SOURCE (§60): never fake hypotheses ---- */
  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 max-w-screen-xl mx-auto space-y-4">
        <h2 className="text-xl font-bold text-foreground tracking-tight">Hypothesis</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Test assumptions against your actual business data.</p>
        <div className="text-center py-12 bg-card border border-border rounded-xl">
          <Database size={22} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-medium text-foreground">Connect a data source to test hypotheses against real data</p>
          <button onClick={() => (setPage as any)?.("data")} className="mt-3 text-xs font-semibold text-primary hover:underline">Go to Data Sources</button>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-foreground tracking-tight">Hypothesis</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Test assumptions against your actual business data.</p>
        </div>
        {status === "done" && verdict && !needMore && !notTestable && (
          <div className="flex flex-wrap items-center gap-2 text-[11px] font-bold">
            <span className="px-2.5 py-1 rounded-full" style={significant ? { background: "rgba(5,150,105,0.12)", color: "#059669" } : verdict === "NOT SUPPORTED" ? { background: "rgba(239,68,68,0.12)", color: "#EF4444" } : { background: "rgba(245,158,11,0.15)", color: "#B45309" }}>
              {verdict.replace(/_/g, " ")}
            </span>
            {r?.strength && <span className="px-2.5 py-1 rounded-full bg-secondary text-foreground">{String(r.strength).toUpperCase()} EVIDENCE</span>}
          </div>
        )}
      </div>

      {/* Question composer (Path B) */}
      <div className="bg-card border border-border rounded-xl p-5 space-y-4">
        <div className="flex items-start gap-3">
          <Beaker size={16} className="text-primary mt-0.5 flex-shrink-0" />
          <textarea
            value={question}
            onChange={(e) => { setQuestion(e.target.value); setHypEdited(false); }}
            placeholder="What would you like to test? e.g. Did the price increase reduce sales?"
            rows={2}
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none"
          />
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium">Dataset:</span>
          <span className="px-2 py-0.5 bg-secondary border border-border rounded-md text-foreground">{dbName}</span>
        </div>
        <div className="flex gap-2">
          <button onClick={() => parseHypothesis()} disabled={status === "running" || status === "parsing" || !question.trim()}
            className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 transition-opacity disabled:opacity-50">
            {status === "parsing" ? "Understanding…" : "Test it"}
          </button>
          <button onClick={() => { setQuestion(""); setHypText(""); setHypEdited(false); setStatus("idle"); setResult(null); setError(""); setPreview(null); setClarify(null); setPickedMetric(""); setPickedDriver(""); }}
            className="bg-secondary text-secondary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-80 transition-opacity border border-border">
            Clear
          </button>
        </div>

        {/* Suggestions (Path A): untested candidates, never facts (§5) */}
        {status === "idle" && (
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <Sparkles size={12} className="text-primary" />
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                {ideaCards.length > 0 ? `Suggested hypotheses — untested (${ideaCards.length})` : "Try an example"}
              </p>
            </div>
            {ideaCards.length > 0 ? (
              <div className="space-y-2">
                {ideaCards.map((card: any, i: number) => {
                  const open = openIdea === i;
                  return (
                    <div key={`${card.text}-${i}`} className="bg-card border border-border rounded-xl overflow-hidden">
                      <button
                        onClick={() => setOpenIdea(open ? null : i)}
                        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-secondary/40 transition-colors text-left"
                      >
                        <span className="w-6 h-6 rounded-full bg-primary/10 text-primary text-[11px] font-bold flex items-center justify-center flex-shrink-0">
                          {i + 1}
                        </span>
                        <span className="flex-1">
                          <span className="block text-sm font-medium text-foreground">{card.text}</span>
                          <span className="block text-[11px] text-muted-foreground mt-0.5 truncate">{card.evidence}</span>
                        </span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-secondary text-muted-foreground uppercase tracking-wide flex-shrink-0">
                          {card.kind}
                        </span>
                        {open ? <ChevronUp size={15} className="text-muted-foreground flex-shrink-0" /> : <ChevronDown size={15} className="text-muted-foreground flex-shrink-0" />}
                      </button>
                      {open && (
                        <div className="border-t border-border px-4 py-3.5 space-y-3 bg-secondary/20">
                          <div className="text-xs text-muted-foreground leading-relaxed">
                            <p className="font-semibold text-foreground mb-1">Suggested hypothesis — not yet tested</p>
                            <p>{card.evidence}</p>
                            {(card.metric || card.driver || card.dimension || card.time_col) && (
                              <p className="mt-1.5">
                                {[
                                  card.metric && `Metric: ${card.metric}`,
                                  card.driver && `Driver: ${card.driver}`,
                                  card.dimension && `Across: ${card.dimension}`,
                                  card.time_col && `Over: ${card.time_col}`,
                                ].filter(Boolean).join(" · ")}
                              </p>
                            )}
                          </div>
                          <button
                            onClick={() => parseHypothesis(card.text)}
                            className="bg-primary text-primary-foreground px-4 py-1.5 rounded-lg text-xs font-semibold hover:opacity-90 transition-opacity"
                          >
                            Test this hypothesis
                          </button>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {(ideas.length > 0 ? ideas : FALLBACK_IDEAS).map((h) => (
                  <button key={h} onClick={() => parseHypothesis(h)}
                    className="text-xs px-3 py-1.5 bg-card border border-border rounded-full text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors">
                    {h}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Preview (§33): ARIA understood → Run Test */}
      {status === "preview" && preview && (
        <div className="bg-card border border-primary/30 rounded-xl p-5 space-y-3 animate-fade-in">
          <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">ARIA understood your hypothesis as</p>
          <p className="text-[15px] font-semibold text-foreground">{preview.statement}</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[11px]">
            <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Target metric</p><p className="font-semibold text-foreground">{String(preview.metric).replace(/_/g, " ")}</p></div>
            <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Potential driver</p><p className="font-semibold text-foreground">{preview.driver ? String(preview.driver).replace(/_/g, " ") : "Auto (best available)"}</p></div>
            <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Analysis</p><p className="font-semibold text-foreground">{String(preview.analysis).replace(/_/g, " ")}</p></div>
            <div className="rounded-lg border border-border px-2.5 py-2"><p className="text-muted-foreground">Data</p><p className="font-semibold text-foreground">{Number(preview.usable_observations).toLocaleString()} usable</p></div>
          </div>
          {preview.needs_more_data && (
            <p className="text-xs text-warning">Only {preview.usable_observations} usable observations (min {preview.min_required}) — the test may return Needs More Data.</p>
          )}
          <div className="flex gap-2">
            <button onClick={() => analyze()} className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90">Run Test</button>
            <button onClick={() => { setStatus("idle"); setPreview(null); }} className="text-xs text-muted-foreground hover:text-foreground px-2">Edit question</button>
          </div>
        </div>
      )}

      {/* Ambiguity (§62): inline pickers, not an error */}
      {status === "clarify" && clarify && (
        <div className="bg-card border border-border rounded-xl p-5 space-y-3 animate-fade-in">
          <p className="text-sm font-semibold text-foreground">{clarify.message}</p>
          {(clarify.options?.metrics?.length > 0) && (
            <div>
              <p className="text-xs text-muted-foreground mb-1.5">Which metric should represent it?</p>
              <div className="flex flex-wrap gap-2">
                {clarify.options.metrics.map((m: any) => (
                  <button key={`${m.table}.${m.column}`} onClick={() => setPickedMetric(m.column)}
                    className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${pickedMetric === m.column ? "bg-primary text-primary-foreground border-primary font-semibold" : "bg-secondary text-foreground border-border hover:border-primary/40"}`}>
                    {String(m.column).replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>
          )}
          {(clarify.options?.drivers?.length > 0) && (
            <div>
              <p className="text-xs text-muted-foreground mb-1.5">Which driver do you mean?</p>
              <div className="flex flex-wrap gap-2">
                {clarify.options.drivers.map((d: any) => (
                  <button key={`${d.table}.${d.column}`} onClick={() => setPickedDriver(d.column)}
                    className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${pickedDriver === d.column ? "bg-primary text-primary-foreground border-primary font-semibold" : "bg-secondary text-foreground border-border hover:border-primary/40"}`}>
                    {String(d.column).replace(/_/g, " ")}
                  </button>
                ))}
              </div>
            </div>
          )}
          <button onClick={() => parseHypothesis(question, pickedMetric, pickedDriver)} disabled={!pickedMetric}
            className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-sm font-semibold hover:opacity-90 disabled:opacity-50">
            Continue
          </button>
        </div>
      )}

      {/* Loading stages (§34) */}
      {(status === "running" || status === "parsing") && status === "running" && (
        <div className="bg-card border border-border rounded-xl p-6 flex flex-col items-center gap-3">
          <Loader2 size={22} className="animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">{LOAD_STAGES[stage]}</p>
        </div>
      )}

      {status === "error" && (
        <div className="bg-card border border-warning/40 rounded-xl p-4 space-y-1.5">
          <p className="text-sm font-semibold text-foreground">{errInfo.title}</p>
          <p className="text-sm text-muted-foreground">{error || errInfo.hint}</p>
          <div className="flex gap-2 pt-1">
            <button onClick={() => (preview ? analyze() : parseHypothesis())} className="text-xs font-semibold text-primary hover:underline">Try again</button>
            <button onClick={() => { setStatus("idle"); setError(""); }} className="text-xs text-muted-foreground hover:text-foreground">Try another hypothesis</button>
          </div>
        </div>
      )}

      {/* NEEDS_MORE_DATA (§61) */}
      {status === "done" && needMore && (
        <div className="bg-card border border-border rounded-xl p-5 space-y-2">
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} className="text-warning" />
            <p className="text-sm font-semibold text-foreground">{result.hypothesis ? `Not enough to test yet: ${result.hypothesis}` : "Not enough to test yet"}</p>
          </div>
          <p className="text-sm text-muted-foreground leading-relaxed">{result.detail}</p>
          <div className="flex gap-2 pt-1">
            <button onClick={() => { setStatus("idle"); }} className="text-xs font-semibold text-primary hover:underline">Try Another Hypothesis</button>
            <button onClick={() => (setPage as any)?.("data")} className="text-xs text-muted-foreground hover:text-foreground">Change Time Range</button>
          </div>
        </div>
      )}

      {/* NOT_TESTABLE (§63/§14) with available fields */}
      {status === "done" && notTestable && (
        <div className="bg-card border border-border rounded-xl p-5 space-y-3">
          <p className="text-sm font-semibold text-foreground">This hypothesis can't be tested with the current data</p>
          <p className="text-sm text-muted-foreground leading-relaxed">{result.detail}</p>
          {availFields.length > 0 && (
            <div>
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Available related fields</p>
              <div className="flex flex-wrap gap-1.5">
                {availFields.slice(0, 12).map((f: any, i: number) => (
                  <span key={i} className="text-[11px] px-2 py-1 rounded-md bg-secondary border border-border text-foreground">{String(f.column).replace(/_/g, " ")}</span>
                ))}
              </div>
            </div>
          )}
          <div className="flex gap-2">
            <button onClick={() => { setStatus("idle"); setResult(null); }} className="text-xs font-semibold text-primary hover:underline">Try Another Hypothesis</button>
            <button onClick={loadAvailFields} className="text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1"><ListChecks size={12} /> View Available Fields</button>
          </div>
        </div>
      )}

      {status === "done" && !needMore && !notTestable && r && (
        <>
          {/* Editable hypothesis */}
          <div className="bg-card border border-border rounded-xl p-4 space-y-2">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Tested hypothesis (editable)</p>
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                value={hypEdited ? hypText : (result.hypothesis || "")}
                onChange={(e) => { setHypText(e.target.value); setHypEdited(true); }}
                className="flex-1 bg-secondary border border-border rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-primary"
              />
              {hypEdited && (
                <button onClick={() => parseHypothesis(hypText)} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-xs font-semibold hover:opacity-90 whitespace-nowrap">
                  Test this version
                </button>
              )}
            </div>
            <p className="text-[11px] text-muted-foreground">Method: {String(r.analysis || "").replace(/_/g, " ")} · {Number(r.n || 0).toLocaleString()} records · {r.table}</p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Data quality */}
            <div className="bg-card border border-border rounded-xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Data Quality</p>
                <span className="text-[11px] text-muted-foreground">{dqChecks.filter((c) => c.done).length} of {dqChecks.length}</span>
              </div>
              {dqChecks.map((c) => (
                <div key={c.label} className="space-y-1.5">
                  <div className="flex items-center gap-2">
                    {c.done ? <CheckCircle size={14} className="text-positive flex-shrink-0" /> : <XCircle size={14} className="text-negative flex-shrink-0" />}
                    <p className="text-[13px] font-medium text-foreground">{c.label}</p>
                  </div>
                  <p className="text-[11px] text-muted-foreground pl-6">{c.sub}</p>
                  <div className="h-1 bg-secondary rounded-full overflow-hidden ml-6">
                    <div className={`h-full rounded-full ${c.done ? "bg-positive" : "bg-negative"}`} style={{ width: c.done ? "100%" : "8%" }} />
                  </div>
                </div>
              ))}
              {prep && (
                <p className="text-[11px] text-muted-foreground pl-0 pt-1">
                  {Number(prep.rows_available || r.n || 0).toLocaleString()} rows available · {Number(prep.usable ?? r.n ?? 0).toLocaleString()} valid observations used.
                </p>
              )}
            </div>

            {/* Summary */}
            <div className="lg:col-span-2 bg-card border border-border rounded-xl p-5">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
                <div className="md:col-span-2 space-y-3">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Summary</p>
                  <p className="text-sm text-foreground leading-relaxed">{result.explanation}</p>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <button onClick={saveCurrent} className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-secondary border border-border text-foreground hover:bg-secondary/70">
                      <Save size={12} /> Save
                    </button>
                    {onAskQuestion && (
                      <button onClick={() => onAskQuestion(`Investigate: ${result.hypothesis} (${r.driver} vs ${r.metric}, ${r.analysis})`)}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-primary text-primary-foreground hover:opacity-90">
                        Ask ARIA <ArrowRight size={12} />
                      </button>
                    )}
                  </div>
                </div>
                <div className="space-y-4 md:border-l md:border-border md:pl-5">
                  <Headline label={r.analysis === "correlation" ? "Correlation" : r.analysis === "trend" ? "Trend slope" : "Gap"} value={r.analysis === "correlation" ? `${Number(r.r) >= 0 ? "+" : ""}${Number(r.r).toFixed(2)}` : r.analysis === "trend" ? `${Number(r.slope_per_period) >= 0 ? "+" : ""}${(Math.round(Number(r.slope_per_period) * 100) / 100).toLocaleString()}` : r.rel_pct !== undefined && r.rel_pct !== null ? `${Number(r.rel_pct) >= 0 ? "+" : ""}${r.rel_pct}%` : "—"} sub="headline result" />
                  <Headline label="Confidence" value={Number(r.p_value) < 0.01 ? "High" : Number(r.p_value) < 0.05 ? "Moderate" : "Low"} sub={r.analysis === "correlation" ? `r² shares ${Math.round(Number(r.r) ** 2 * 100)}% movement` : `p = ${Number(r.p_value) < 0.001 ? "<0.001" : Number(r.p_value).toFixed(3)}`} />
                </div>
              </div>
            </div>
          </div>

          {/* Visualization */}
          <div className="bg-card border border-border rounded-xl p-5">
            <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">Evidence chart</p>
            {viz?.type === "scatter" && (
              <ResponsiveContainer width="100%" height={260}>
                <ScatterChart>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                  <XAxis dataKey="x" name={viz.x} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} label={{ value: viz.x, position: "insideBottom", offset: -5, fontSize: 11, fill: axis }} />
                  <YAxis dataKey="y" name={viz.y} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                  <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }} />
                  <Scatter data={viz.points} fill="var(--primary)" fillOpacity={0.6} />
                  {trendLine && <Line type="linear" data={trendLine} dataKey="y" stroke="var(--primary)" strokeWidth={2} dot={false} />}
                </ScatterChart>
              </ResponsiveContainer>
            )}
            {viz?.type === "line" && (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={lineData}>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} minTickGap={24} />
                  <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                  <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }} />
                  <Line type="monotone" dataKey="actual" stroke="var(--primary)" strokeWidth={2} dot={false} name={viz.y} />
                </LineChart>
              </ResponsiveContainer>
            )}
            {(viz?.type === "bar" || viz?.type === "comparison" || viz?.type === "grouped") && barData.length > 0 && (
              <ResponsiveContainer width="100%" height={Math.max(180, barData.length * 44)}>
                <BarChart data={barData} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={110} />
                  <Tooltip contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }} />
                  <Bar dataKey="value" radius={[0, 5, 5, 0]}>
                    {barData.map((_: any, i: number) => (
                      <Cell key={i} fill="var(--primary)" fillOpacity={i === 0 ? 1 : 0.55} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* Segments */}
          {segments.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5 space-y-3">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Where is the effect strongest?</p>
              <div className="flex flex-wrap gap-2">
                {segments.map((s: any, i: number) => (
                  <button key={s.dimension} onClick={() => setSegDim(i)}
                    className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${i === Math.min(segDim, segments.length - 1) ? "bg-primary text-primary-foreground border-primary font-semibold" : "bg-secondary text-muted-foreground border-border hover:text-foreground"}`}>
                    {s.dimension.replace(/_/g, " ")}
                  </button>
                ))}
              </div>
              {activeSeg && (
                <div className="space-y-2.5">
                  {activeSeg.groups.map((g: any) => {
                    const max = Math.max(...activeSeg.groups.map((x: any) => x.value), 1);
                    return (
                      <div key={g.label} className="space-y-1">
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-foreground font-medium">{g.label} <span className="text-muted-foreground">· n={g.n}</span></span>
                          <span className="text-foreground font-semibold">{Number(g.value).toLocaleString()}</span>
                        </div>
                        <div className="h-2 bg-secondary rounded-full overflow-hidden">
                          <div className="h-full rounded-full bg-primary" style={{ width: `${Math.max(3, (g.value / max) * 100)}%` }} />
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* What-if simulation */}
          {showWhatIf && (
            <div id="hyp-whatif" className="bg-card border border-border rounded-xl p-5 space-y-3">
              <div className="flex items-center gap-2">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">What-if simulation</p>
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-secondary text-muted-foreground">SIMULATION</span>
              </div>
              <p className="text-xs text-muted-foreground">Slide to see what happens if {r.driver.replace(/_/g, " ")} changes. Assumes the measured link holds.</p>
              <div className="flex flex-wrap items-center gap-4">
                <input type="range" min={-50} max={50} step={5} value={simPct}
                  onChange={(e) => setSimPct(Number(e.target.value))}
                  className="flex-1 min-w-[160px] accent-[var(--primary)]" aria-label="Driver change percent" />
                <span className={`text-lg font-bold w-20 text-right ${simPct >= 0 ? "text-positive" : "text-negative"}`}>
                  {simPct >= 0 ? "+" : ""}{simPct}%
                </span>
              </div>
              {simOutcome && (
                <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                  <SimCard label="Baseline" value={simOutcome.base} sub={`avg ${r.metric.replace(/_/g, " ")}`} />
                  <SimCard label={`With ${simPct >= 0 ? "+" : ""}${simPct}% ${r.driver.replace(/_/g, " ")}`} value={simOutcome.scenario} sub={`${simOutcome.delta >= 0 ? "+" : ""}${simOutcome.delta.toFixed(1)} vs baseline`} hot />
                  <div className="border border-border rounded-xl p-3.5 space-y-1">
                    <p className="text-xs text-muted-foreground">Keep in mind</p>
                    <p className="text-xs text-foreground leading-relaxed">Linear projection from the measured slope — a what-if, not a forecast.</p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Limitations */}
          {(result.limitations || []).length > 0 && (
            <div className="bg-secondary/50 border border-border rounded-xl p-4 space-y-1.5">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Limitations</p>
              {(result.limitations || []).map((l: string, i: number) => (
                <p key={i} className="text-xs text-muted-foreground leading-relaxed">· {l}</p>
              ))}
            </div>
          )}

          {/* Evidence (s.txt): shared disclosure, closed by default */}
          <Evidence
            sections={[
              { title: "Data analyzed", body: `${prep ? `${Number(prep.rows_available || r.n).toLocaleString()} rows scanned, ${Number(prep.usable ?? r.n).toLocaleString()} valid observations on the tested columns` : `${Number(r.n).toLocaleString()} valid observations`} in ${r.table}. Missing values elsewhere were left untouched.` },
              { title: "Key observation", body: result.explanation },
              { title: "Analysis method", body: `${String(r.analysis || "").replace(/_/g, " ")}${r.analysis === "correlation" ? " (Pearson primary, Spearman robustness check)" : r.analysis === "group_comparison" ? " (Welch t primary, Mann-Whitney check)" : ""}. Confidence in the result: ${confidenceWord(r.p_value)}.` },
              { title: "Confidence", body: `Statistical values (rounded): p ${Number(r.p_value) < 0.001 ? "<0.001" : `≈ ${Number(r.p_value).toFixed(3)}`} · n = ${Number(r.n).toLocaleString()}${r.r !== undefined ? ` · relationship ≈ ${Number(r.r).toFixed(2)}` : ""}${r.cohens_d !== undefined ? ` · group gap ≈ ${Number(r.cohens_d).toFixed(2)} standard deviations` : ""}.` },
              { title: "Assumptions & limits", body: "Outliers kept and reported. Association only — never proof of cause. Verdict rule: clear effect + expected direction → Supported; otherwise Not Supported or Inconclusive." },
            ]}
          />

          {/* Next actions (§§43–45): structured context, not bare sentences */}
          <div className="bg-card border border-border rounded-xl p-4">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2.5">Next actions</p>
            <div className="flex flex-wrap gap-2">
              {activeSeg && (
                <ActionBtn label={`Explore: ${activeSeg.dimension}`} onClick={() => document.getElementById("hyp-segments")?.scrollIntoView({ behavior: "smooth" })} />
              )}
              {showWhatIf && (
                <ActionBtn label="Run what-if" onClick={() => document.getElementById("hyp-whatif")?.scrollIntoView({ behavior: "smooth" })} />
              )}
              <ActionBtn label="Forecast impact" onClick={() => {
                try { sessionStorage.setItem("aria_forecast_prefill", JSON.stringify({ metric: r.metric, driver: r.driver, source: { tables: [r.table] } })); } catch {}
                (setPage as any)?.("predictive");
              }} />
              <ActionBtn label="Create prescription" onClick={() => {
                try { sessionStorage.setItem("aria_insight_handoff", JSON.stringify({ metric: r.metric, dimensions: [r.driver], question: result.hypothesis, source: { tables: [r.table] } })); } catch {}
                (setPage as any)?.("prescription");
              }} />
              {onAskQuestion && (
                <>
                  <ActionBtn label="Investigate driver" onClick={() => onAskQuestion(`What drives ${r.metric}? Focus on ${r.driver}.`)} />
                  <ActionBtn label="Ask ARIA" onClick={() => onAskQuestion(`Explain this finding: ${result.hypothesis}`)} />
                </>
              )}
            </div>
            <span id="hyp-segments" />
          </div>

          {/* Saved */}
          <div className="bg-card border border-border rounded-xl p-4 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Saved hypotheses ({saved.length})</p>
              {result && !needMore && !notTestable && (
                <button onClick={saveCurrent} className="flex items-center gap-1.5 text-xs font-semibold text-primary hover:underline">
                  <Save size={12} /> Save this one
                </button>
              )}
            </div>
            {saved.length === 0 && <p className="text-xs text-muted-foreground">Nothing saved yet — results you save will live here.</p>}
            {saved.map((s) => (
              <div key={s.id} className="flex items-center gap-2 text-xs border border-border rounded-lg px-3 py-2">
                <span className={`font-bold ${s.verdict === "SUPPORTED" ? "text-positive" : s.verdict === "NOT SUPPORTED" ? "text-negative" : "text-warning"}`}>
                  {String(s.verdict).replace(/_/g, " ")}
                </span>
                <span className="text-foreground truncate flex-1">{s.hypothesis}</span>
                <button onClick={() => parseHypothesis(s.question)} className="text-primary hover:underline whitespace-nowrap">Re-run</button>
                <button onClick={() => {
                  const next = saved.filter((x) => x.id !== s.id);
                  setSaved(next);
                  try { localStorage.setItem(SAVED_KEY, JSON.stringify(next)); } catch {}
                }} className="text-muted-foreground hover:text-negative" aria-label="Delete saved">
                  <Trash2 size={12} />
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Headline({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div>
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="text-2xl font-bold text-foreground">{value}</p>
      <p className="text-[11px] text-muted-foreground">{sub}</p>
    </div>
  );
}

function SimCard({ label, value, sub, hot }: { label: string; value: number; sub: string; hot?: boolean }) {
  return (
    <div className={`border rounded-xl p-3.5 space-y-1 ${hot ? "border-primary/40 bg-primary/5" : "border-border"}`}>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-xl font-bold text-foreground">{value.toLocaleString(undefined, { maximumFractionDigits: 1 })}</p>
      <p className="text-xs text-muted-foreground">{sub}</p>
    </div>
  );
}

function ActionBtn({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button onClick={onClick} className="text-xs font-semibold px-3 py-1.5 rounded-lg bg-secondary border border-border text-foreground hover:bg-secondary/70 transition-colors">
      {label}
    </button>
  );
}
