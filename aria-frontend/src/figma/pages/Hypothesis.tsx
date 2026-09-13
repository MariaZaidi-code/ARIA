import { useState, useEffect, useRef, useMemo } from "react";
import {
  Loader2, Database, Search, AlertTriangle,
  ArrowRight, ArrowLeft, RefreshCw, TrendingDown, TrendingUp,
  Minus, Layers, AlertCircle, FileText, CheckCircle2,
} from "lucide-react";
import { XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, LineChart, Line, BarChart, Bar, Cell, Brush } from "recharts";
import { useTheme } from "../App";
import Evidence from "../components/Evidence";
import { ChartFrame, BizTooltip } from "../components/charts";

/* =====================================================================
   ARIA Hypothesis — automatic investigation workspace (t.txt).
   Page loads WITH analysis: detected changes -> ranked explanations ->
   evidence -> deep investigation. Manual input uses the same engine.
   No orange, no chat bubbles, motion restrained, dark-mode native.
   ===================================================================== */

const FALLBACK_IDEAS = [
  "Why did sales decline?",
  "What caused the change in orders?",
  "Why is one category underperforming?",
  "What explains the recent change?",
];

const ERROR_MAP: Record<string, { title: string; hint: string }> = {
  NO_CONNECTION: { title: "No data source connected", hint: "Connect PostgreSQL, MySQL, or upload a CSV to investigate real data." },
  INVALID_SOURCE: { title: "Couldn't read this source", hint: "Reconnect your data source, then try again." },
  ANALYSIS_FAILED: { title: "We couldn't complete this investigation", hint: "ARIA couldn't analyze the current data. Your connection is still available." },
  TIMEOUT: { title: "The investigation timed out", hint: "Try a narrower question or reconnect, then run again." },
  INTERNAL_ERROR: { title: "Something went wrong", hint: "Your data was not changed. Try again." },
};

const STRENGTH_STYLE: Record<string, { background: string; color: string; dot: string }> = {
  "Strong evidence": { background: "rgba(5,150,105,0.10)", color: "#047857", dot: "#059669" },
  "Moderate evidence": { background: "rgba(47,111,173,0.10)", color: "#1E5AA8", dot: "#2F6FAD" },
  "Limited evidence": { background: "var(--secondary)", color: "var(--secondary-foreground)", dot: "var(--muted-foreground)" },
  "Insufficient evidence": { background: "var(--secondary)", color: "var(--muted-foreground)", dot: "var(--muted-foreground)" },
};

const LOAD_STAGES = [
  "Understanding your data",
  "Finding important changes",
  "Comparing business segments",
  "Evaluating possible explanations",
];

interface Props {
  insightResult?: any;
  onAskQuestion?: (question: string) => void;
  connectionStatus?: string;
}

export default function Hypothesis({ onAskQuestion, connectionStatus = "not-connected" }: Props) {
  const { isDark, setPage } = useTheme() as any;
  const [question, setQuestion] = useState("");
  const [investigating, setInvestigating] = useState(false);
  const [loadStage, setLoadStage] = useState(0);
  const [investigation, setInvestigation] = useState<any>(null);
  const [autoEvents, setAutoEvents] = useState<any[]>([]);
  const [analyzedAt, setAnalyzedAt] = useState("");
  const [autoLoading, setAutoLoading] = useState(false);
  const [deepDive, setDeepDive] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [errorCode, setErrorCode] = useState("");
  const [ideas, setIdeas] = useState<string[]>(FALLBACK_IDEAS);
  const [dbName, setDbName] = useState("Connected Data");
  const [sourceLabel, setSourceLabel] = useState("");
  // Autocomplete
  const [acOpen, setAcOpen] = useState(false);
  const [acIndex, setAcIndex] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const acRef = useRef<HTMLDivElement>(null);
  const prefillDone = useRef(false);

  const authHeader = () => {
    const token = localStorage.getItem("aria_auth_token");
    return { Authorization: `Bearer ${token}` };
  };

  // Auto-run on page load: the page opens WITH analysis, not an empty box.
  useEffect(() => {
    const token = localStorage.getItem("aria_auth_token");
    if (token) {
      fetch("/api/session/status", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => {
          if (d.db_name) setDbName(d.db_name);
          const parts: string[] = [];
          if (d.source_type === "document" && d.document_name) parts.push(`PDF · ${d.document_name}`);
          else if (d.db_name && !String(d.db_name).match(/^[0-9a-f-]{36}$/)) parts.push(d.db_name);
          if (d.linked_db_name) parts.push(`+ ${d.linked_db_name}`);
          setSourceLabel(parts.length > 1 ? "2 data sources connected" : parts.join(" "));
        })
        .catch(() => {});
      fetch("/api/hypothesis/suggest", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => {
          const texts: string[] = [];
          if (d.ok && Array.isArray(d.cards)) {
            for (const c of d.cards) {
              if (c?.text) texts.push(c.text);
              if (c?.evidence && texts.length < 8) texts.push(c.evidence);
            }
          }
          if (d.ok && Array.isArray(d.suggestions)) texts.push(...d.suggestions);
          if (texts.length) setIdeas(texts.slice(0, 10));
        })
        .catch(() => {});
      if (connectionStatus === "connected") loadAuto();
    }
    if (!prefillDone.current) {
      prefillDone.current = true;
      try {
        const raw = sessionStorage.getItem("aria_hypothesis_prefill");
        if (raw) {
          const h = JSON.parse(raw);
          sessionStorage.removeItem("aria_hypothesis_prefill");
          const q = h.question || (h.metric ? `Why did ${h.metric} change?` : "");
          if (q) {
            setQuestion(q);
            setTimeout(() => runInvestigation(q), 350);
          }
        }
      } catch { /* best-effort */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionStatus]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (acRef.current && !acRef.current.contains(e.target as Node)) setAcOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  const loadAuto = async () => {
    setAutoLoading(true);
    setLoadStage(0);
    const timer = setInterval(() => setLoadStage((s) => Math.min(s + 1, LOAD_STAGES.length - 1)), 1600);
    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/hypotheses/auto", { headers: { Authorization: `Bearer ${token || ""}` } });
      const data = await res.json().catch(() => ({}));
      clearInterval(timer);
      if (res.ok && data.ok) {
        setInvestigation(data);
        setAutoEvents(data.events || []);
        setAnalyzedAt(data.analyzed_at || "just now");
        setErrorCode(""); setError("");
      }
    } catch { /* auto is best-effort; manual input remains */ }
    finally {
      clearInterval(timer);
      setAutoLoading(false);
    }
  };

  const runInvestigation = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || investigating) return;
    setQuestion(text);
    setAcOpen(false);
    setInvestigating(true);
    setLoadStage(0);
    setInvestigation(null);
    setAutoEvents([]);
    setDeepDive(null);
    setError(""); setErrorCode("");
    const timer = setInterval(() => setLoadStage((s) => Math.min(s + 1, LOAD_STAGES.length - 1)), 1600);
    try {
      const res = await fetch("/api/hypotheses/investigate", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeader() },
        body: JSON.stringify({ question: text }),
      });
      const data = await res.json().catch(() => ({}));
      clearInterval(timer);
      if (!res.ok || data.ok === false) {
        const code = data?.code || "ANALYSIS_FAILED";
        setErrorCode(code);
        setError(data?.detail || "");
        return;
      }
      setInvestigation(data);
      setAnalyzedAt("just now");
    } catch (err: any) {
      clearInterval(timer);
      setErrorCode("ANALYSIS_FAILED");
      setError(err?.message || "");
    } finally {
      clearInterval(timer);
      setInvestigating(false);
    }
  };

  // ---- Data-driven autocomplete (t.txt §autocomplete) ----
  const acPool = useMemo(() => {
    const pool: { text: string; kind: string; group: string }[] = [];
    // Recovery questions from the last run come first: the backend built
    // them from resolved schema roles, so each one is guaranteed runnable.
    for (const s of (investigation?.suggestions || []).slice(0, 3)) {
      if (typeof s === "string" && s) pool.push({ text: s, kind: "search", group: "Try instead" });
    }
    for (const ev of autoEvents.slice(0, 4)) {
      const m = String(ev.metric || "").replace(/_/g, " ");
      const dir = (ev.change_pct || 0) < 0 ? "decline" : "change";
      pool.push({ text: `Why did ${m} ${dir}?`, kind: "trend", group: "Detected changes" });
      if (ev.table) pool.push({ text: `Which segment drove the ${m} ${dir}?`, kind: "segment", group: "Explore a driver" });
    }
    const dims = new Set<string>();
    for (const h of (investigation?.hypotheses || [])) {
      const m = h?.chart?.dimension;
      if (m && !dims.has(m) && dims.size < 3) {
        dims.add(m);
        pool.push({ text: `Why did ${String(m).replace(/_/g, " ")} perform poorly?`, kind: "segment", group: "Investigate a segment" });
      }
    }
    for (const s of ideas.slice(0, 3)) {
      if (!pool.some((p) => p.text === s)) pool.push({ text: s, kind: "trend", group: "Suggested" });
    }
    return pool.slice(0, 10);
  }, [autoEvents, investigation, ideas]);

  const acFiltered = useMemo(() => {
    const q = question.trim().toLowerCase();
    if (!q) return acPool.slice(0, 5);
    const words = q.split(/\s+/).filter(Boolean);
    const scored = acPool.map((p) => {
      const t = p.text.toLowerCase();
      let s = 0;
      if (t.startsWith(q)) s += 3;
      else if (t.includes(q)) s += 2;
      for (const w of words) if (w.length > 2 && t.includes(w)) s += 1;
      return { p, s };
    }).filter((x) => x.s > 0).sort((a, b) => b.s - a.s);
    return scored.slice(0, 5).map((x) => x.p);
  }, [question, acPool]);

  const acGroups = useMemo(() => {
    const out: { group: string; items: typeof acFiltered }[] = [];
    for (const item of acFiltered) {
      const g = out.find((x) => x.group === item.group);
      if (g) g.items.push(item);
      else out.push({ group: item.group, items: [item] });
    }
    return out;
  }, [acFiltered]);

  const flatAc = acFiltered;
  const KIND_ICON: Record<string, any> = { trend: TrendingDown, segment: Layers, alert: AlertCircle, doc: FileText, search: Search };

  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowDown" && acOpen && flatAc.length) { e.preventDefault(); setAcIndex((i) => (i + 1) % flatAc.length); }
    else if (e.key === "ArrowUp" && acOpen && flatAc.length) { e.preventDefault(); setAcIndex((i) => (i - 1 + flatAc.length) % flatAc.length); }
    else if (e.key === "Escape") { setAcOpen(false); }
    else if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (acOpen && flatAc[acIndex]) runInvestigation(flatAc[acIndex].text);
      else runInvestigation();
    }
  };

  const renderCompletion = (full: string) => {
    const q = question.trim();
    if (!q || !full.toLowerCase().startsWith(q.toLowerCase())) return <span>{full}</span>;
    return <span>{full.slice(0, q.length)}<strong className="text-foreground">{full.slice(q.length)}</strong></span>;
  };

  const errInfo = ERROR_MAP[errorCode] || ERROR_MAP.ANALYSIS_FAILED;
  const obs = investigation?.observation || {};
  const hyps = investigation?.hypotheses || [];
  const busy = investigating || autoLoading;
  const deepHyp = deepDive !== null ? hyps[deepDive] : null;

  const followUps = (h: any) => {
    const out: string[] = [];
    if (h?.chart?.dimension) out.push(`Which ${String(h.chart.dimension).replace(/_/g, " ")} contributed most?`);
    out.push(`Did the change affect all regions?`);
    if (obs.metric) out.push(`Did order volume or average value change for ${String(obs.metric).replace(/_/g, " ")}?`);
    return out.slice(0, 3);
  };

  if (connectionStatus !== "connected") {
    return (
      <div className="p-6 md:p-8 max-w-screen-xl mx-auto">
        <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Workspace</p>
        <h2 className="mt-1 text-2xl font-bold text-foreground tracking-tight">Hypothesis</h2>
        <p className="mt-1 text-sm text-muted-foreground max-w-xl">Explore what may be driving important changes in your business.</p>
        <div className="mt-6 text-center py-14 bg-card border border-border rounded-2xl shadow-sm">
          <Database size={22} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-semibold text-foreground">Connect your data to investigate</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">ARIA needs a connected data source before it can detect business patterns and possible explanations.</p>
          <div className="mt-4 flex items-center justify-center gap-3">
            <button onClick={() => (setPage as any)?.("data")} className="text-xs font-semibold px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90">Connect data</button>
            <button onClick={() => (setPage as any)?.("dashboard")} className="text-xs font-medium text-muted-foreground hover:text-foreground">Explore how it works</button>
          </div>
        </div>
      </div>
    );
  }

  // ---- Deep investigation view ----
  if (deepHyp) {
    const i = deepDive as number;
    return (
      <div className="p-6 md:p-8 max-w-screen-xl mx-auto space-y-5">
        <button onClick={() => setDeepDive(null)} className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted-foreground hover:text-foreground">
          <ArrowLeft size={13} /> Back to hypotheses
        </button>
        <div>
          <p className="text-[11px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Investigating</p>
          <h2 className="mt-1 text-xl font-bold text-foreground tracking-tight">{deepHyp.title}</h2>
          <span className="mt-2 inline-flex px-2.5 py-1 rounded-full text-[11px] font-bold"
            style={(STRENGTH_STYLE[deepHyp.strength] || STRENGTH_STYLE["Limited evidence"]) as React.CSSProperties}>
            {deepHyp.strength}
          </span>
        </div>
        <section className="bg-card border border-border rounded-2xl shadow-sm p-5 md:p-6">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">What ARIA found</p>
          <p className="mt-2 text-sm text-foreground leading-relaxed">{deepHyp.explanation}</p>
        </section>
        {deepHyp.chart?.type === "hbar" && (deepHyp.chart?.groups || []).length > 0 && (
          <section className="bg-card border border-border rounded-2xl shadow-sm p-5 md:p-6">
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Contribution</p>
            <div className="mt-3">
              <ResponsiveContainer width="100%" height={Math.max(180, (deepHyp.chart.groups || []).length * 42)}>
                <BarChart data={deepHyp.chart.groups} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="label" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={120} />
                  <Tooltip content={<BizTooltip />} cursor={{ fill: "var(--secondary)" }} />
                  <Bar dataKey="value" radius={[0, 5, 5, 0]} name="Value">
                    {(deepHyp.chart.groups || []).map((_: any, k: number) => (
                      <Cell key={k} fill="var(--primary)" fillOpacity={k === 0 ? 1 : 0.6} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <section className="bg-card border border-border rounded-2xl shadow-sm p-5">
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Supporting evidence</p>
            {(deepHyp.supporting || []).map((s: string, j: number) => (
              <p key={j} className="mt-1.5 text-[13px] text-foreground leading-relaxed">· {s}</p>
            ))}
          </section>
          <section className="bg-card border border-border rounded-2xl shadow-sm p-5">
            <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">What weakens this explanation</p>
            {((deepHyp.contradictory || []).length > 0 ? deepHyp.contradictory : ["No contradictory evidence found in the available data."]).map((s: string, j: number) => (
              <p key={j} className="mt-1.5 text-[13px] text-foreground leading-relaxed">· {s}</p>
            ))}
          </section>
        </div>
        <section className="bg-card border border-border rounded-2xl shadow-sm p-5">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">What remains unknown</p>
          {(deepHyp.limitations || ["Whether this pattern holds outside the observed period."]).map((s: string, j: number) => (
            <p key={j} className="mt-1.5 text-[13px] text-muted-foreground leading-relaxed">· {s}</p>
          ))}
          <div className="mt-3">
            <Evidence
              sections={[
                { title: "Data analyzed", body: `${(obs.n || 0).toLocaleString()} observations of ${String(obs.metric || "the metric").replace(/_/g, " ")}${obs.table ? ` in ${obs.table}` : ""}.` },
                { title: "Key observation", body: obs.text || "See the investigation summary." },
                { title: "Assumptions & limits", body: ((deepHyp.limitations || []).join(" ") || "Association only — never proof of cause.") },
              ]}
              technical={`Ranked ${i + 1} of ${hyps.length} by measured support. Metrics: ${JSON.stringify(deepHyp.metrics || {})}. For analyst review.`}
            />
          </div>
        </section>
        <section className="bg-card border border-border rounded-2xl shadow-sm p-5">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Continue investigating</p>
          <div className="mt-2.5 flex flex-wrap gap-2">
            {followUps(deepHyp).map((q) => (
              <button key={q} onClick={() => { setDeepDive(null); runInvestigation(q); }}
                className="text-xs font-medium px-3.5 py-2 bg-secondary border border-border rounded-full text-foreground hover:border-primary/50 transition-colors">
                {q}
              </button>
            ))}
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-screen-xl mx-auto space-y-5">
      {/* Compact header: title + source + analyzed + refresh */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-xl font-bold text-foreground tracking-tight">Hypothesis</h2>
          <p className="mt-0.5 text-[13px] text-muted-foreground">Explore what may be driving important changes in your business.</p>
        </div>
        <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
          {sourceLabel && (
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-secondary border border-border text-foreground font-medium">
              <span className="w-1.5 h-1.5 rounded-full bg-positive inline-block" />
              {sourceLabel}
            </span>
          )}
          {analyzedAt && <span>Analysis updated {analyzedAt}</span>}
          <button onClick={() => loadAuto()} disabled={autoLoading}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-border text-foreground font-medium hover:bg-secondary transition-colors disabled:opacity-50"
            title="Re-scan the data">
            <RefreshCw size={11} className={autoLoading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      {/* Investigation command bar + autocomplete */}
      <div className="bg-card border border-border rounded-2xl shadow-sm p-4 md:p-5" ref={acRef}>
        <div className="flex items-center gap-3 rounded-xl border border-border bg-secondary/40 px-4 py-3 focus-within:border-primary/60 transition-colors">
          <Search size={15} className="text-muted-foreground flex-shrink-0" />
          <textarea
            ref={inputRef}
            value={question}
            onChange={(e) => { setQuestion(e.target.value); setAcOpen(true); setAcIndex(0); }}
            onFocus={() => setAcOpen(true)}
            onKeyDown={onInputKey}
            placeholder="Ask ARIA why something changed..."
            rows={1}
            aria-expanded={acOpen}
            aria-label="Investigation question"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none"
          />
          <button onClick={() => runInvestigation()} disabled={investigating || !question.trim()}
            className="bg-primary text-primary-foreground px-5 py-2 rounded-lg text-[13px] font-semibold hover:opacity-90 disabled:opacity-40 flex-shrink-0">
            Investigate
          </button>
        </div>
        {acOpen && flatAc.length > 0 && (
          <div className="mt-2 rounded-xl border border-border bg-card shadow-lg overflow-hidden">
            {acGroups.map((g) => (
              <div key={g.group}>
                {acGroups.length > 1 && (
                  <p className="px-4 pt-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{g.group}</p>
                )}
                {g.items.map((s) => {
                  const Icon = KIND_ICON[s.kind] || Search;
                  const active = flatAc.indexOf(s) === acIndex;
                  return (
                    <button key={s.text}
                      onMouseEnter={() => setAcIndex(flatAc.indexOf(s))}
                      onClick={() => runInvestigation(s.text)}
                      className={`w-full flex items-center gap-2.5 px-4 py-2 text-left text-[13px] transition-colors ${active ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground"}`}>
                      <Icon size={13} className="flex-shrink-0" />
                      <span className="truncate">{renderCompletion(s.text)}</span>
                    </button>
                  );
                })}
              </div>
            ))}
          </div>
        )}
        {acOpen && acFiltered.length === 0 && question.trim() && (
          <div className="mt-2 rounded-xl border border-border bg-card shadow-lg px-4 py-3 flex items-center justify-between gap-3">
            <span className="text-[13px] text-muted-foreground truncate">Investigate your question: “{question.trim()}”</span>
            <button onClick={() => runInvestigation()}
              className="text-xs font-semibold px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground hover:opacity-90 flex-shrink-0">
              Investigate →
            </button>
          </div>
        )}
      </div>

      {/* Staged loader */}
      {busy && (
        <div className="bg-card border border-border rounded-2xl shadow-sm p-6 md:p-8">
          <p className="text-sm font-semibold text-foreground text-center">Analyzing your business data</p>
          <div className="mt-4 max-w-sm mx-auto space-y-2.5">
            {LOAD_STAGES.map((s, i) => (
              <div key={s} className="flex items-center gap-2.5 text-[13px]">
                {i < loadStage ? (
                  <CheckCircle2 size={14} className="text-positive flex-shrink-0" />
                ) : i === loadStage ? (
                  <Loader2 size={14} className="animate-spin text-primary flex-shrink-0" />
                ) : (
                  <span className="w-3.5 h-3.5 rounded-full border border-border flex-shrink-0" />
                )}
                <span className={i <= loadStage ? "text-foreground" : "text-muted-foreground"}>{s}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {errorCode && !busy && (
        <div className="bg-card border border-negative/30 rounded-2xl shadow-sm p-5">
          <p className="text-sm font-semibold text-foreground">{errInfo.title}</p>
          <p className="mt-1 text-sm text-muted-foreground">{error || errInfo.hint}</p>
          <div className="flex gap-2 mt-3">
            <button onClick={() => runInvestigation()} className="text-xs font-semibold px-4 py-2 rounded-lg bg-primary text-primary-foreground hover:opacity-90">Try again</button>
            <button onClick={() => (setPage as any)?.("data")} className="text-xs font-medium px-4 py-2 rounded-lg border border-border text-foreground hover:bg-secondary">View data source</button>
          </div>
        </div>
      )}

      {/* ARIA detected strip */}
      {!busy && !errorCode && autoEvents.length > 0 && !investigation && (
        <section>
          <h3 className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">ARIA detected</h3>
          <p className="text-xs text-muted-foreground mt-0.5 mb-2.5">Important changes and patterns found in your data.</p>
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            {autoEvents.slice(0, 4).map((ev: any, i: number) => {
              const down = (ev.change_pct || 0) < 0;
              const flat = Math.abs(ev.change_pct || 0) <= 1;
              return (
                <button key={i} onClick={() => runInvestigation(`Why did ${String(ev.metric).replace(/_/g, " ")} change?`)}
                  className="text-left bg-card border border-border rounded-xl shadow-sm p-4 hover:border-primary/40 hover:shadow-md transition-all">
                  <p className="text-xs font-medium text-muted-foreground capitalize truncate">{String(ev.metric).replace(/_/g, " ")}</p>
                  <p className={`mt-1 text-xl font-bold tabular-nums flex items-center gap-1.5 ${flat ? "text-foreground" : down ? "text-negative" : "text-positive"}`}>
                    {flat ? <Minus size={15} /> : down ? <TrendingDown size={15} /> : <TrendingUp size={15} />}
                    {down ? "↓" : flat ? "→" : "↑"} {Math.abs(ev.change_pct || 0).toFixed(0)}%
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">{ev.periods || ""} periods{ev.anomaly ? " · unusual latest" : ""}</p>
                </button>
              );
            })}
          </div>
        </section>
      )}

      {/* Observation overview */}
      {!busy && !errorCode && investigation?.ok && !investigation?.insufficient && obs.text && (
        <section className="bg-card border border-border rounded-2xl shadow-sm p-5 md:p-6">
          <p className="text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Investigation</p>
          <p className="mt-2 text-lg font-semibold text-foreground tracking-tight leading-snug">{obs.text}</p>
          <div className="mt-4 grid grid-cols-3 gap-3 max-w-lg">
            <div className="rounded-xl bg-secondary/60 border border-border/60 px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Records</p>
              <p className="mt-0.5 text-base font-bold text-foreground tabular-nums">{(obs.n || 0).toLocaleString()}</p>
            </div>
            <div className="rounded-xl bg-secondary/60 border border-border/60 px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Metric</p>
              <p className="mt-0.5 text-base font-bold text-foreground truncate">{String(obs.metric || "—").replace(/_/g, " ")}</p>
            </div>
            <div className="rounded-xl bg-secondary/60 border border-border/60 px-3 py-2.5">
              <p className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">Explanations</p>
              <p className="mt-0.5 text-base font-bold text-foreground tabular-nums">{hyps.length}</p>
            </div>
          </div>
          {obs.chart?.points?.length > 0 && (
            <div className="mt-4 rounded-xl border border-border/70 p-4">
              <ChartFrame
                title={`${String(obs.chart.y || obs.metric || "Metric").replace(/_/g, " ")} over time`}
                explanation="Hover any point for its period and value. Drag the slider to zoom."
                height={220}
              >
                <ResponsiveContainer width="100%" height={220}>
                  <LineChart data={obs.chart.points}>
                    <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} minTickGap={28} />
                    <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                    <Tooltip content={<BizTooltip metricNames={{ actual: obs.chart.y }} />} />
                    <Line type="monotone" dataKey="actual" stroke="var(--primary)" strokeWidth={2} dot={false} name={obs.chart.y} />
                    {obs.chart.points.length > 12 && (
                      <Brush dataKey="label" height={24} stroke="var(--primary)" travellerWidth={10} />
                    )}
                  </LineChart>
                </ResponsiveContainer>
              </ChartFrame>
            </div>
          )}
        </section>
      )}

      {/* Possible explanations */}
      {!busy && !errorCode && hyps.length > 0 && (
        <section className="space-y-3">
          <div>
            <h3 className="text-[15px] font-bold text-foreground tracking-tight">Possible explanations</h3>
            <p className="text-xs text-muted-foreground mt-0.5">ARIA ranked the strongest patterns associated with the changes above.</p>
          </div>
          {hyps.map((h: any, i: number) => {
            const tone = STRENGTH_STYLE[h.strength] || STRENGTH_STYLE["Limited evidence"];
            const m = h.metrics || {};
            const metricChips = [
              m.contribution_share !== undefined ? `≈${Math.round(m.contribution_share * 100)}% of move` : null,
              m.change_pct !== undefined && m.change_pct !== null ? `${m.change_pct >= 0 ? "+" : ""}${Math.round(m.change_pct)}%` : null,
              m.volume_change_pct !== undefined ? `vol ${m.volume_change_pct >= 0 ? "+" : ""}${Math.round(m.volume_change_pct)}%` : null,
            ].filter(Boolean).slice(0, 3);
            return (
              <article key={i} className="bg-card border border-border rounded-2xl shadow-sm p-5 animate-fade-in">
                <div className="flex gap-4">
                  <span className="hidden sm:flex w-9 h-9 rounded-xl bg-secondary border border-border items-center justify-center text-xs font-bold text-muted-foreground flex-shrink-0">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div className="flex-1 min-w-0 space-y-2.5">
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <h4 className="text-[15px] font-semibold text-foreground tracking-tight">{h.title || "Possible explanation"}</h4>
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-bold flex-shrink-0" style={{ background: tone.background, color: tone.color }}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: tone.dot }} />
                        {h.strength || "Limited evidence"}
                      </span>
                    </div>
                    <p className="text-[13px] text-foreground leading-relaxed">
                      {(h.explanation || "ARIA found a pattern worth a closer look.").split(/(?<=[.!?])\s+/).slice(0, 2).join(" ")}
                    </p>
                    {metricChips.length > 0 && (
                      <div className="flex flex-wrap gap-1.5">
                        {metricChips.map((chip: string, j: number) => (
                          <span key={j} className="text-[11px] font-semibold px-2.5 py-1 rounded-lg bg-secondary border border-border/60 text-foreground tabular-nums">{chip}</span>
                        ))}
                      </div>
                    )}
                    {h.chart?.type === "hbar" && (h.chart?.groups || []).length > 0 && (
                      <div className="rounded-xl border border-border/70 p-3">
                        <ResponsiveContainer width="100%" height={Math.max(120, Math.min(200, (h.chart.groups || []).length * 34))}>
                          <BarChart data={h.chart.groups.slice(0, 6)} layout="vertical">
                            <CartesianGrid strokeDasharray="3 3" stroke={grid} horizontal={false} />
                            <XAxis type="number" hide />
                            <YAxis type="category" dataKey="label" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={100} />
                            <Tooltip content={<BizTooltip />} cursor={{ fill: "var(--secondary)" }} />
                            <Bar dataKey="value" radius={[0, 4, 4, 0]} name="Value">
                              {(h.chart.groups || []).slice(0, 6).map((_: any, k: number) => (
                                <Cell key={k} fill="var(--primary)" fillOpacity={k === 0 ? 1 : 0.6} />
                              ))}
                            </Bar>
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                    )}
                    <div className="flex items-center gap-2 pt-0.5">
                      <button onClick={() => setDeepDive(deepDive === i ? null : i)}
                        className="text-[11px] font-semibold text-muted-foreground hover:text-foreground transition-colors">
                        {deepDive === i ? "Hide evidence" : "View evidence"}
                      </button>
                      <span className="text-border">·</span>
                      <button onClick={() => setDeepDive(i)}
                        className="text-[11px] font-semibold text-primary hover:underline inline-flex items-center gap-0.5">
                        Investigate <ArrowRight size={11} />
                      </button>
                    </div>
                    {deepDive === i && (
                      <div className="border-t border-border pt-3 space-y-3 animate-fade-in">
                        <div>
                          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Why ARIA is considering this</p>
                          <p className="mt-1 text-xs text-foreground leading-relaxed">{h.explanation}</p>
                        </div>
                        {(h.supporting || []).length > 0 && (
                          <div>
                            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Supporting evidence</p>
                            {(h.supporting || []).slice(0, 4).map((s: string, j: number) => (
                              <p key={j} className="mt-1 text-xs text-foreground leading-relaxed">· {s}</p>
                            ))}
                          </div>
                        )}
                        {((h.contradictory || []).length > 0) && (
                          <div>
                            <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">Evidence against</p>
                            {(h.contradictory || []).map((s: string, j: number) => (
                              <p key={j} className="mt-1 text-xs text-foreground leading-relaxed">· {s}</p>
                            ))}
                          </div>
                        )}
                        <div>
                          <p className="text-[10px] font-bold text-muted-foreground uppercase tracking-wider">What ARIA cannot determine</p>
                          <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                            {((h.limitations || []).join(" ") || "Whether this pattern holds outside the observed period, or what external factors may be involved.")}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {onAskQuestion && (
                            <button onClick={() => onAskQuestion(`Explain this finding: ${h.title}`)}
                              className="text-[11px] font-semibold px-3 py-1.5 rounded-lg bg-secondary border border-border text-foreground hover:bg-secondary/70">Ask ARIA</button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </article>
            );
          })}
          {(investigation?.needed_data || []).length > 0 && (
            <details className="rounded-xl border border-border bg-secondary/40 px-4 py-3">
              <summary className="cursor-pointer text-xs font-semibold text-muted-foreground hover:text-foreground">What would confirm this?</summary>
              <div className="mt-2 space-y-1">
                {(investigation.needed_data || []).map((n: string, j: number) => (
                  <p key={j} className="text-xs text-foreground">· {n}</p>
                ))}
              </div>
            </details>
          )}
        </section>
      )}

      {/* No strong hypotheses */}
      {!busy && !errorCode && investigation?.ok && (investigation?.insufficient || hyps.length === 0) && (
        <div className="bg-card border border-border rounded-2xl shadow-sm p-6 md:p-8">
          <p className="text-[15px] font-semibold text-foreground">No strong explanations detected</p>
          <p className="mt-1.5 text-sm text-muted-foreground leading-relaxed max-w-lg">
            {investigation.detail || "ARIA found changes in your data, but there isn't enough evidence to confidently identify a likely driver."}
          </p>
          <p className="mt-3 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">What ARIA found</p>
          <p className="mt-1 text-[13px] text-foreground">{investigation.observation?.text || "The data was scanned."}</p>
          {(investigation.needed_data || []).length > 0 && (
            <>
              <p className="mt-3 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">What is missing</p>
              {(investigation.needed_data || []).map((n: string, j: number) => (
                <p key={j} className="mt-1 text-[13px] text-muted-foreground">· {n}</p>
              ))}
            </>
          )}
          <p className="mt-4 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">Explore manually</p>
          <p className="text-xs text-muted-foreground mt-1">Type a question above — ARIA will investigate it against the same evidence.</p>
          {(investigation.suggestions || []).length > 0 && (
            <>
              <p className="mt-4 text-[11px] font-bold uppercase tracking-[0.12em] text-muted-foreground">These will run against your data</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {(investigation.suggestions || []).map((s: string) => (
                  <button key={s} onClick={() => runInvestigation(s)}
                    className="text-xs font-medium px-3.5 py-2 bg-secondary border border-border rounded-full text-foreground hover:border-primary/50 transition-colors">
                    {s}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {!investigation && !busy && !errorCode && (
        <div className="text-center py-12 bg-card border border-dashed border-border rounded-2xl">
          <Search size={20} className="mx-auto text-muted-foreground mb-3" />
          <p className="text-sm font-semibold text-foreground">Ask ARIA why something changed.</p>
          <p className="text-xs text-muted-foreground mt-1 max-w-md mx-auto">Type a question above, or pick a suggested investigation built from your data.</p>
        </div>
      )}
    </div>
  );
}
