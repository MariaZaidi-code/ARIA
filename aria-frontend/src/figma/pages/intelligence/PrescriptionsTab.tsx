/* Prescriptions tab: generate-from-context + scenario playground + saved list.
   All actions, numbers, ranges and honesty notes come from the prescription
   engine (POST /api/prescriptions/analyze|scenario, GET context|saved) —
   this file only renders. Slider bounds come from the backend-declared
   scenario_meta.supported_pct (or the engine-measured impact.observed
   range); when the backend declares no range the slider is replaced by a
   plain number input — never a hardcoded ±%. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion, MotionConfig } from "framer-motion";
import {
  ClipboardList, Play, RefreshCw, Bookmark, SlidersHorizontal, Info,
  Trash2, FlaskConical, Sparkles, ChevronRight, Eye, TrendingUp, TrendingDown,
  BarChart3, ShieldCheck, AlertTriangle, RotateCcw,
} from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, ReferenceLine } from "recharts";
import { prescriptionApi, normalizeApiError } from "../../../services/api";
import {
  asList, strOf, numOf, humanize, titleCase, fmtMetric, getNoSchemaInfo,
  businessError,
} from "../../lib/intelHelpers";
import {
  Card, EmptyState, LoadingPanel, ErrorPanel, NoDatasetPanel, Field,
  StatPill, selectCls, inputCls, btnPrimary, btnGhost, StaggerGroup,
  StaggerItem, fadeUp,
} from "./cards";
import type { IntelTab } from "../Intelligence";
import RxCaseDrawer from "./RxCaseDrawer";
import { parseRxHandoff, type RxHandoff } from "./useExplore";

export interface PrescriptionsTabProps {
  meta: any;
  onGoto: (t: IntelTab) => void;
  onAsk: (q: string) => void;
  /* Explore→Prescriptions handoff (metric/breakdown/segment). When absent,
     the URL hash (rx_metric/rx_driver/rx_segment/rx_value) is used.
     Values are matched against the live backend options — never invented. */
  exploreHandoff?: RxHandoff | null;
}

const RX_SAVED_KEY = "aria_rx_saved";

function loadLocalSaved(): any[] {
  try {
    const v = JSON.parse(localStorage.getItem(RX_SAVED_KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

function storeLocalSaved(items: any[]): void {
  try {
    localStorage.setItem(RX_SAVED_KEY, JSON.stringify(items || []));
  } catch { /* best-effort */ }
}

/** Mini baseline-vs-scenario bar chart for prescription cards. */
function MiniRxChart({ baseline, scenario, delta, metric }: {
  baseline: number | null; scenario: number | null; delta: number | null; metric?: string;
}) {
  if (baseline === null && scenario === null) return null;
  const data = [
    { name: "Current", value: baseline ?? 0, fill: "#94a3b8" },
    { name: "Projected", value: scenario ?? 0, fill: (delta ?? 0) >= 0 ? "#22c55e" : "#ef4444" },
  ];
  const maxVal = Math.max(...data.map((d) => Math.abs(d.value)));
  const fmt = (v: number) => {
    if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
    if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
    return v.toFixed(0);
  };
  return (
    <div className="h-16 w-full mt-2">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 0, top: 0, bottom: 0 }} barSize={14}>
          <XAxis type="number" hide domain={[0, maxVal * 1.15 || 1]} />
          <YAxis type="category" dataKey="name" width={65} tick={{ fontSize: 10, fill: "#64748b" }} axisLine={false} tickLine={false} />
          <Tooltip
            formatter={(v: number) => [fmt(v), "Value"]}
            contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e2e8f0" }}
            cursor={false}
          />
          <Bar dataKey="value" radius={[0, 4, 4, 0]}>
            {data.map((entry, idx) => (
              <Cell key={idx} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Confidence dots — visual representation of confidence level. */
export function ConfidenceDots({ level }: { level: string }) {
  const s = (level || "").toLowerCase();
  const filled = s === "high" ? 3 : s === "moderate" || s === "medium" ? 2 : 1;
  return (
    <span className="inline-flex items-center gap-0.5" title={`Confidence: ${level || "Unknown"}`}>
      {[1, 2, 3].map((i) => (
        <span key={i} className={`inline-block w-1.5 h-1.5 rounded-full ${i <= filled ? "bg-blue-600" : "bg-slate-200"}`} />
      ))}
      <span className="ml-1 text-[10px] text-slate-500">{titleCase(level || "—")}</span>
    </span>
  );
}

/** Risk badge — plain language risk indicator. */
function RiskBadge({ risk }: { risk: string }) {
  const r = (risk || "").toLowerCase();
  if (r === "high") return <span className="inline-flex items-center gap-1 text-[10px] text-red-700 bg-red-50 border border-red-200 rounded-full px-1.5 py-0.5"><AlertTriangle size={10} /> High risk</span>;
  if (r === "moderate" || r === "medium") return <span className="inline-flex items-center gap-1 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded-full px-1.5 py-0.5"><ShieldCheck size={10} /> Moderate risk</span>;
  return <span className="inline-flex items-center gap-1 text-[10px] text-green-700 bg-green-50 border border-green-200 rounded-full px-1.5 py-0.5"><ShieldCheck size={10} /> Low risk</span>;
}

const optVal = (x: any): string =>
  strOf(typeof x === "string" ? x : x?.column || x?.name || x?.label);

export default function PrescriptionsTab({ meta, onGoto, onAsk, exploreHandoff }: PrescriptionsTabProps) {
  /* ---- dynamic context (pickers) ---- */
  const [ctx, setCtx] = useState<any>(null);
  const [ctxLoading, setCtxLoading] = useState(true);
  const [ctxError, setCtxError] = useState("");
  const [ctxId, setCtxId] = useState("");

  const loadCtx = useCallback(async () => {
    setCtxLoading(true);
    setCtxError("");
    setCtxId("");
    try {
      const r = await prescriptionApi.context();
      setCtx((r as any).data || null);
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setCtxError(norm.message);
      setCtxId(norm.requestId);
      setCtx(null);
    } finally {
      setCtxLoading(false);
    }
  }, []);
  useEffect(() => { loadCtx(); }, [loadCtx]);

  /* Metric/driver/dimension options: prescription context first (it carries
     drivers + tables); intelligence meta as fallback so the tab still works
     when context is unreachable. Never hardcoded column names. */
  const metricOpts: string[] = useMemo(() => {
    const fromCtx = asList(ctx?.metrics).map(optVal).filter(Boolean);
    if (fromCtx.length) return Array.from(new Set(fromCtx));
    return asList(meta?.metrics ?? meta?.measures)
      .map((x) => strOf(typeof x === "string" ? x : x?.name || x?.label))
      .filter(Boolean);
  }, [ctx, meta]);
  const driverOpts: string[] = useMemo(() => {
    const fromCtx = asList(ctx?.drivers).map(optVal).filter(Boolean);
    return Array.from(new Set(fromCtx));
  }, [ctx]);
  const dimOpts: string[] = useMemo(() => {
    const fromCtx = asList(ctx?.dimensions).map(optVal).filter(Boolean);
    if (fromCtx.length) return Array.from(new Set(fromCtx));
    return asList(meta?.breakdowns ?? meta?.dimensions)
      .map((x) => strOf(typeof x === "string" ? x : x?.column || x?.name || x?.label))
      .filter(Boolean);
  }, [ctx, meta]);

  const [metric, setMetric] = useState("");
  const [driver, setDriver] = useState("");
  const [segField, setSegField] = useState("");
  /* Segment value is free text: the backend validates it against real
     segments — the UI never invents segment names. */
  const [segValue, setSegValue] = useState("");

  /* ---- Explore→Prescriptions handoff (no new endpoints) ----
     Prefill the pickers from Explore context: the explicit prop first,
     else the URL hash (rx_metric/rx_driver/rx_segment/rx_value — see
     useExplore.parseRxHandoff). Each value is matched against the live
     backend options — never invented. Applied once so later user edits
     are never overwritten. */
  const handoffRef = useRef(false);
  const [handoffNote, setHandoffNote] = useState("");
  useEffect(() => {
    if (handoffRef.current) return;
    if (!metricOpts.length) return;
    const h = exploreHandoff || parseRxHandoff();
    if (!h) return;
    const matchOpt = (opts: string[], v: string): string => {
      const s = strOf(v);
      if (!s) return "";
      return opts.find((o) => o === s) || opts.find((o) => o.toLowerCase() === s.toLowerCase()) || "";
    };
    let applied = false;
    const hm = matchOpt(metricOpts, strOf(h.metric));
    if (hm) {
      setMetric(hm);
      applied = true;
    }
    const hd = matchOpt(driverOpts, strOf(h.driver));
    if (hd) {
      setDriver(hd);
      applied = true;
    } else {
      /* A breakdown that is not a driver may still be a valid segment. */
      const asSeg = matchOpt(dimOpts, strOf(h.driver));
      if (asSeg && !segField) {
        setSegField(asSeg);
        applied = true;
      }
    }
    const hsf = matchOpt(dimOpts, strOf(h.segmentField));
    if (hsf) {
      setSegField(hsf);
      if (strOf(h.segmentValue)) setSegValue(strOf(h.segmentValue));
      applied = true;
    }
    if (applied) {
      handoffRef.current = true;
      setHandoffNote("Prefilled from your Explore view — adjust anything, then Run analysis.");
    }
  }, [metricOpts, driverOpts, dimOpts, exploreHandoff, segField]);

  useEffect(() => {
    if (metric && driver === metric) setDriver("");
  }, [metric, driver]);

  /* ---- analyze ---- */
  const [analyzing, setAnalyzing] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [analyzeError, setAnalyzeError] = useState("");
  const [analyzeId, setAnalyzeId] = useState("");
  const [question, setQuestion] = useState("");
  const [presets, setPresets] = useState<any[]>([]);
  const [levers, setLevers] = useState<any[]>([]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await (prescriptionApi as any).presets();
        if (!cancelled) setPresets(asList((r as any)?.data?.presets));
      } catch {
        if (!cancelled) setPresets([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!metric) {
      setLevers([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const r = await (prescriptionApi as any).levers({ metric });
        if (!cancelled) setLevers(asList((r as any)?.data?.levers));
      } catch {
        if (!cancelled) setLevers([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [metric]);

  /* Segment value suggestions: distinct values the backend already sent
     (context dimensions, current evidence) surface as datalist hints;
     free text still works when the backend sent nothing. Never hardcoded —
     every suggestion below is dynamic from a live endpoint payload. */
  const segSuggestions: string[] = useMemo(() => {
    const out: string[] = [];
    const push = (v: unknown) => {
      const s = strOf(typeof v === "string" ? v : (v as any)?.value ?? (v as any)?.label ?? "");
      if (s && !out.includes(s)) out.push(s);
    };
    for (const d of asList(ctx?.dimensions)) for (const v of asList((d as any)?.values)) push(v);
    for (const v of asList((ctx as any)?.segment_values)) push(v);
    for (const pr of asList(presets)) {
      push((pr as any)?.segment_value);
      push((pr as any)?.value);
    }
    for (const p of asList(result?.prescriptions)) {
      const ev = (p as any)?.evidence;
      if (ev && typeof ev === "object") {
        push(ev.top);
        push(ev.bottom);
        const sg = ev.segment;
        if (sg && typeof sg === "object") push(sg.value);
        else push(sg);
      }
    }
    return out.slice(0, 20);
  }, [ctx, presets, result]);

  const runAnalyze = useCallback(async (ov?: { metric?: string; driver?: string }) => {
    const m = strOf(ov?.metric || metric);
    const d = ov && "driver" in ov ? strOf(ov.driver) : driver;
    if (!m || analyzing) return;
    if (ov?.metric) setMetric(ov.metric);
    if (ov && "driver" in ov) setDriver(strOf(ov.driver));
    setAnalyzing(true);
    setAnalyzeError("");
    setAnalyzeId("");
    setHandoffNote("");
    setResult(null);
    setScResult(null);
    setScError("");
    try {
      const q = `What should I consider for ${m}${d ? ` (driver: ${d})` : ""}?`;
      setQuestion(q);
      const payload: Record<string, unknown> = { metric: m, question: q };
      if (d) {
        payload.driver = d;
        payload.dimensions = [d];
      }
      if (segField) {
        if (!driver) payload.dimensions = [segField];
        if (segValue.trim()) {
          payload.segment = { field: segField, value: segValue.trim() };
        }
      }
      const r = await prescriptionApi.analyze(payload);
      setResult((r as any).data || null);
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setAnalyzeError(norm.message);
      setAnalyzeId(norm.requestId);
    } finally {
      setAnalyzing(false);
    }
  }, [metric, driver, segField, segValue, analyzing]);

  const prescriptions: any[] = useMemo(
    () => asList(result?.prescriptions),
    [result],
  );
  const refused = !!result && (result.ok === false || result.status === "no_prescription" || prescriptions.length === 0);
  const scenarioCands = useMemo(
    () => prescriptions.filter((p) => strOf(p?.action_type).toLowerCase() === "scenario"),
    [prescriptions],
  );

  /* ---- saved (server list, localStorage fallback with real payloads) ---- */
  const [savedServer, setSavedServer] = useState<any[] | null>(null);
  const [savedLocal, setSavedLocal] = useState<any[]>(() => loadLocalSaved());
  const [savingId, setSavingId] = useState<string | null>(null);
  const [saveMsg, setSaveMsg] = useState("");
  const [caseRx, setCaseRx] = useState<any>(null);

  const loadSaved = useCallback(async () => {
    try {
      const r = await prescriptionApi.listSaved();
      setSavedServer(asList((r as any).data?.saved ?? (r as any).data));
    } catch {
      setSavedServer(null);
      setSavedLocal(loadLocalSaved());
    }
  }, []);
  useEffect(() => { loadSaved(); }, [loadSaved]);

  const savedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const s of savedServer || []) {
      const id = strOf(s?.id || s?.prescription_id || s?.title);
      if (id) ids.add(id);
    }
    for (const s of savedLocal) {
      const id = strOf(s?.id || s?.title);
      if (id) ids.add(id);
    }
    return ids;
  }, [savedServer, savedLocal]);

  const saveRx = useCallback(async (p: any) => {
    const id = strOf(p?.id || p?.title);
    if (!id || savingId) return;
    setSavingId(id);
    setSaveMsg("");
    try {
      await prescriptionApi.save(p, question || undefined);
      await loadSaved();
      setSaveMsg("Recommendation saved.");
    } catch (e: any) {
      /* Server save failed — keep the REAL payload locally instead of losing it. */
      const entry = { ...p, id: p?.id || `rx_local_${Date.now()}`, question, saved_at: new Date().toISOString() };
      const next = [entry, ...loadLocalSaved()].slice(0, 50);
      storeLocalSaved(next);
      setSavedLocal(next);
      setSaveMsg("Server save failed — kept locally instead.");
    } finally {
      setSavingId(null);
    }
  }, [savingId, question, loadSaved]);

  const unsaveRx = useCallback(async (id: string, local: boolean) => {
    if (!id) return;
    setSaveMsg("");
    if (local) {
      const next = loadLocalSaved().filter((s) => strOf(s?.id || s?.title) !== id);
      storeLocalSaved(next);
      setSavedLocal(next);
      return;
    }
    try {
      await prescriptionApi.unsave(id);
      await loadSaved();
    } catch (e: any) {
      setSaveMsg(businessError(e?.message) || "ARIA couldn't remove this saved item.");
    }
  }, [loadSaved]);

  const updateSavedRx = useCallback(async (id: string, patch: Record<string, string>) => {
    const r = await prescriptionApi.updateSaved(id, patch);
    await loadSaved();
    /* Refresh the open case from the updated server list so the drawer
       shows persisted owner/priority/review values, not just local state. */
    try {
      const items = asList((r as any).data?.saved ?? []);
      const fresh = items.find((s: any) => strOf(s?.id) === id);
      if (fresh) setCaseRx(fresh);
    } catch { /* best-effort */ }
  }, [loadSaved]);

  /* ---- scenario playground ---- */
  const [selId, setSelId] = useState("");
  const selected = useMemo(
    () => scenarioCands.find((p) => strOf(p?.id) === selId) || scenarioCands[0] || null,
    [scenarioCands, selId],
  );
  useEffect(() => {
    if (!selId && scenarioCands.length) setSelId(strOf(scenarioCands[0]?.id));
  }, [scenarioCands, selId]);

  /* Slider bounds: backend scenario_meta.supported_pct first; else derive
     from the engine-measured impact.observed range (capped at the engine's
     ±50 hard limit); else NO slider (number input) — never hardcoded. */
  const supportRange = useMemo(() => {
    const sm = result?.scenario_meta?.supported_pct;
    const smin = numOf(sm?.min);
    const smax = numOf(sm?.max);
    if (smin !== null && smax !== null && smax > smin) {
      return { min: smin, max: smax, from: "backend scenario_meta" };
    }
    const obs = selected?.impact?.observed;
    const omin = numOf(obs?.min);
    const omax = numOf(obs?.max);
    const omean = numOf(obs?.mean);
    if (omin !== null && omax !== null && omean !== null && omean !== 0) {
      const down = Math.max(0, Math.min(50, ((omean - omin) / Math.abs(omean)) * 100));
      const up = Math.max(0, Math.min(50, ((omax - omean) / Math.abs(omean)) * 100));
      if (up > 0 || down > 0) {
        return {
          min: -Math.round(down * 10) / 10,
          max: Math.round(up * 10) / 10,
          from: "engine-measured observed range",
        };
      }
    }
    return null;
  }, [result, selected]);

  const [pct, setPct] = useState<number>(10);
  const [scRunning, setScRunning] = useState(false);
  const [scResult, setScResult] = useState<any>(null);
  const [scError, setScError] = useState("");
  const [scErrorId, setScErrorId] = useState("");

  useEffect(() => {
    if (supportRange) {
      setPct((v) => Math.max(supportRange.min, Math.min(supportRange.max, v)));
    }
  }, [supportRange]);

  const runScenario = useCallback(async () => {
    if (!selected || !result || scRunning) return;
    const table = strOf(result.table);
    const m = strOf(result.metric);
    const d = strOf(selected?.driver || (selected?.evidence as any)?.driver || driver);
    if (!table || !m || !d) {
      setScError("This card has no modeled driver to run a scenario on.");
      return;
    }
    setScRunning(true);
    setScError("");
    setScErrorId("");
    setScResult(null);
    try {
      const payload: Record<string, unknown> = {
        table, metric: m, driver: d,
        changes: [{ field: d, operation: "percent", value: pct }],
      };
      if (segField && segValue.trim()) {
        payload.filters = [{ field: segField, operator: "equals", value: segValue.trim() }];
      }
      const jr = result.join_ref;
      if (jr && strOf(jr.table) && strOf(jr.self_col) && strOf(jr.other_col)) {
        payload.join = { table: strOf(jr.table), self_col: strOf(jr.self_col), other_col: strOf(jr.other_col) };
      }
      const r = await prescriptionApi.runScenario(payload);
      const dd: any = (r as any).data;
      if (dd && dd.ok === false) {
        setScError(strOf(dd.detail || "This scenario is not supported for the selection."));
      } else {
        setScResult(dd);
      }
    } catch (e: any) {
      const norm = normalizeApiError({ message: e?.message }, e?.status || 0, null);
      setScError(norm.message);
      setScErrorId(norm.requestId);
    } finally {
      setScRunning(false);
    }
  }, [selected, result, driver, segField, segValue, pct, scRunning]);

  const scFirst = useMemo(() => asList(scResult?.scenarios)[0] || null, [scResult]);

  /* ---- display-safe render helpers (new contract first, legacy fallback).
     Non-technical card order per prescription:
       1. Problem  (display.problem_text, legacy story/summary fallback)
       2. Why      (display.why_text bullets, always visible, max 3;
                    legacy why_summary fallback)
       3. Action (display.action_text) + Outcome (display.outcome_text)
       4. "See the numbers" expander — plain labels only (Link strength /
          Data points / Chance noise), limitations in plain words,
          Engine risk. Raw r/p/slope keys never reach the UI. ---- */
  const rxApi: any = prescriptionApi as any;
  const dispOf = (p: any): any =>
    p?.display && typeof p.display === "object" ? p.display : {};
  const detailsOf = (p: any): any =>
    p?.details && typeof p.details === "object" ? p.details : {};
  const problemOf = (p: any): string => {
    try {
      const v = strOf(rxApi.problemOf?.(p));
      if (v) return v;
    } catch { /* fall through to legacy fields */ }
    return strOf(p?.summary_plain || p?.story || p?.summary);
  };
  const whyBulletsOf = (p: any, max = 3): string[] => {
    try {
      const v = rxApi.whyBulletsOf?.(p, max);
      if (Array.isArray(v)) return v.map((x) => strOf(x)).filter(Boolean).slice(0, max);
    } catch { /* fall through to legacy field */ }
    const legacy = strOf(dispOf(p).why_summary || p?.why_summary);
    return legacy ? [legacy] : [];
  };
  const plainLabelOf = (key: string): string => {
    try {
      const v = strOf(rxApi.plainNumberLabel?.(key));
      if (v) return v;
    } catch { /* fall through */ }
    /* Never leak single-letter statistic keys (r/p) to end users. */
    if (/^[a-z]$/i.test(String(key ?? "").trim())) return "Detail";
    return humanize(key);
  };
  const numbersOf = (p: any): Record<string, unknown> => {
    const n = detailsOf(p)?.numbers;
    return n && typeof n === "object" ? n : {};
  };
  const limsOf = (p: any): string[] => {
    const det = detailsOf(p);
    const src = asList(det.limitations).length ? det.limitations : p?.limitations;
    return asList(src).map((x) => strOf(typeof x === "string" ? x : x?.text || x?.label)).filter(Boolean);
  };

  /* Expander row formatting: plain-words for chance-noise (never a raw
     p-value), labeled rows otherwise via the existing fmt helpers
     (money-aware) — never invented numbers. */
  const fmtNumberRow = (key: string, v: unknown): string => {
    if (typeof v === "string") return v;
    const k = key.toLowerCase();
    if (k === "p_value" || k === "p") {
      try {
        const w = strOf(rxApi.chanceNoiseWords?.(v));
        if (w) return w;
      } catch { /* fall through to numeric */ }
    }
    const n = numOf(v);
    if (n === null) return strOf(v);
    if (k === "n" || k === "n_points") return Math.round(n).toLocaleString();
    if (k.includes("pct") || k.includes("gap") || k.includes("share") || k.includes("momentum") || k === "rel_pct") {
      return `${n >= 0 ? "+" : ""}${Math.round(n * 10) / 10}%`;
    }
    if (k === "p_value") return n < 0.001 ? "<0.001" : n.toFixed(3);
    if (k === "effect_r" || k === "r" || k === "spearman_r" || k === "slope") {
      return `${n >= 0 ? "+" : ""}${Math.round(n * 100) / 100}`;
    }
    if (["baseline", "scenario", "delta", "first", "last", "mean", "driver_value"].includes(k)) {
      return fmtMetric(n, result?.metric || metric);
    }
    return strOf(v);
  };

  const confTone = (c: unknown): "up" | "info" | "neutral" | "warn" => {
    const s = String(c ?? "").toLowerCase();
    if (s === "high") return "up";
    if (s === "moderate" || s === "medium") return "info";
    if (s === "low" || s === "limited" || s === "early") return "warn";
    return "neutral";
  };

  /* Refusal contract: headline + computed alternatives (one-click re-run).
     Legacy string alternatives keep their navigation behavior as fallback. */
  const refusalObj: any =
    result && typeof result.refusal === "object" ? result.refusal : null;
  const refusalAlts: any[] = asList(refusalObj?.alternatives);
  const legacyAlts: string[] = asList(result?.alternatives)
    .map((a: any) => strOf(typeof a === "string" ? a : a?.label))
    .filter(Boolean);

  const savedCombined: { item: any; local: boolean }[] = useMemo(() => {
    const out: { item: any; local: boolean }[] = [];
    for (const s of savedServer || []) out.push({ item: s, local: false });
    for (const s of savedLocal) out.push({ item: s, local: true });
    return out.slice(0, 20);
  }, [savedServer, savedLocal]);

  if (ctxLoading) return <LoadingPanel label="Loading prescription options…" />;
  if (ctxError && metricOpts.length === 0) {
    return <ErrorPanel message={ctxError} requestId={ctxId} onRetry={loadCtx} retryLabel="Reload options" />;
  }
  if (metricOpts.length === 0) {
    const noSchema = getNoSchemaInfo(ctx || meta);
    return <NoDatasetPanel onRetry={loadCtx} hint={noSchema.isNoSchema ? noSchema.hint : undefined} />;
  }

  return (
    <MotionConfig reducedMotion="user">
      <div className="space-y-4">
        <div className="text-[11px] text-slate-400 flex items-center gap-1">
          <span>Intelligence</span><ChevronRight size={11} /><span className="text-slate-600 font-medium">Prescriptions</span>
        </div>

        {/* Metric cards — click to select, advanced options appear after */}
        {!result && !analyzing && (
          <div>
            <h3 className="text-[13px] font-semibold text-[#0F2440] tracking-tight mb-2">
              Pick a metric to get recommendations
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
              {metricOpts.map((m) => {
                const active = metric === m;
                return (
                  <button
                    key={m}
                    onClick={() => { setMetric(m); setDriver(""); setSegField(""); setSegValue(""); setResult(null); setAnalyzeError(""); }}
                    className={`group relative text-left rounded-xl border p-3 transition-all ${active
                      ? "border-blue-500 bg-blue-50 ring-2 ring-blue-200 shadow-sm"
                      : "border-slate-200 bg-white hover:border-blue-300 hover:shadow-sm"
                    }`}
                    aria-label={`Get prescriptions for ${humanize(m)}`}
                  >
                    <p className={`text-[12.5px] font-semibold leading-snug ${active ? "text-blue-700" : "text-[#0F2440] group-hover:text-blue-700"}`}>
                      {humanize(m)}
                    </p>
                    <p className="text-[10.5px] text-slate-400 mt-0.5">Click to analyze</p>
                    {active && <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-blue-500" />}
                  </button>
                );
              })}
            </div>
            {handoffNote && (
              <p className="mt-2 text-[11.5px] font-medium text-blue-700" role="status">{handoffNote}</p>
            )}
          </div>
        )}

        {/* Advanced options + Run button — only after metric selected and before results */}
        {metric && !result && !analyzing && (
          <motion.div variants={fadeUp} initial="hidden" animate="show">
            <Card className="p-4 md:p-5">
              <div className="flex items-start justify-between gap-3 flex-wrap">
                <div>
                  <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
                    <ClipboardList size={14} className="text-blue-700" /> Analysis for {humanize(metric)}
                  </h3>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Optionally pick a driver or segment — or just run with auto settings.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <button onClick={() => { setMetric(""); setDriver(""); setSegField(""); setSegValue(""); setResult(null); setAnalyzeError(""); }} className={btnGhost} aria-label="Change metric">
                    <RotateCcw size={13} /> Change metric
                  </button>
                  <button onClick={loadCtx} className={btnGhost} aria-label="Reload options">
                    <RefreshCw size={13} /> Reload
                  </button>
                </div>
              </div>
              <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 items-end">
                <Field label="Driver (optional — auto if blank)" htmlFor="rx-driver">
                  <select id="rx-driver" value={driver} onChange={(e) => setDriver(e.target.value)} className={selectCls} aria-label="Driver">
                    <option value="">Auto (strongest evidence)</option>
                    {driverOpts.filter((d) => d !== metric).map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
                  </select>
                  {levers.length > 0 && (
                    <div className="mt-1.5 flex items-center gap-1 flex-wrap" aria-label="Lever testability">
                      {levers.slice(0, 6).map((l: any, i: number) => {
                        const st = strOf(l?.status);
                        const cls = st === "testable"
                          ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                          : st === "needs-data"
                            ? "bg-amber-50 text-amber-700 border-amber-200"
                            : "bg-slate-50 text-slate-500 border-slate-200";
                        return (
                          <button
                            key={i}
                            title={strOf(l?.reason)}
                            onClick={() => { if (st === "testable") setDriver(strOf(l?.column)); }}
                            className={`text-[10.5px] font-medium px-2 py-0.5 rounded-full border ${cls}`}
                          >
                            {humanize(strOf(l?.column))} · {st === "testable" ? "testable" : st === "needs-data" ? "needs data" : "not a lever"}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </Field>
                <Field label="Segment field (optional)" htmlFor="rx-seg">
                  <select id="rx-seg" value={segField} onChange={(e) => { setSegField(e.target.value); setSegValue(""); }} className={selectCls} aria-label="Segment field">
                    <option value="">No segment</option>
                    {dimOpts.map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
                  </select>
                </Field>
                <div className="min-w-0">
                  <button onClick={() => void runAnalyze()} disabled={analyzing} className={`${btnPrimary} w-full !h-[40px]`} aria-label="Run prescription analysis">
                    {analyzing ? "Running…" : "Run Analysis"} <Play size={13} />
                  </button>
                </div>
              </div>
              {segField && (
                <div className="mt-3 max-w-sm">
                  <Field label={`Segment value for ${humanize(segField)} (optional)`} htmlFor="rx-segval">
                    <input
                      id="rx-segval" value={segValue} onChange={(e) => setSegValue(e.target.value)}
                      placeholder="e.g. a real segment name…" className={inputCls} aria-label="Segment value"
                      list={segSuggestions.length ? "rx-segval-list" : undefined} autoComplete="off"
                    />
                    {segSuggestions.length > 0 && (
                      <datalist id="rx-segval-list">
                        {segSuggestions.map((s) => <option key={s} value={s} />)}
                      </datalist>
                    )}
                  </Field>
                </div>
              )}
            </Card>
          </motion.div>
        )}

        {/* Suggested quick-start (presets) — only before any metric selected */}
        {presets.length > 0 && !metric && !result && !analyzing && (
          <div>
            <p className="text-[11px] text-slate-400 mb-1.5">Or try a suggested analysis:</p>
            <div className="flex items-center gap-1.5 flex-wrap" aria-label="Suggested starting questions">
              {presets.slice(0, 4).map((p: any, i: number) => (
                <button
                  key={i}
                  onClick={() => {
                    if (strOf(p?.metric)) setMetric(strOf(p.metric));
                    setDriver("");
                    setTimeout(() => void runAnalyze({ metric: strOf(p?.metric) }), 60);
                  }}
                  className="text-[11.5px] font-medium text-blue-700 border border-blue-200 rounded-full px-2.5 py-1 hover:bg-blue-50"
                  aria-label={`Start: ${strOf(p?.question)}`}
                >
                  {strOf(p?.question)}
                </button>
              ))}
            </div>
          </div>
        )}

        {analyzing && (
          <Card className="p-4 md:p-5">
            <div className="flex items-center gap-3">
              <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              <div>
                <p className="text-[13px] font-semibold text-[#0F2440]">Analyzing {humanize(metric)}…</p>
                <p className="text-[11px] text-slate-500">Testing drivers against your data, checking evidence gates.</p>
              </div>
            </div>
          </Card>
        )}
        {!analyzing && analyzeError && (
          <Card className="p-4 md:p-5">
            <ErrorPanel message={analyzeError} requestId={analyzeId} onRetry={() => void runAnalyze()} retryLabel="Run again" />
          </Card>
        )}

        {/* Honest refusal renders as guidance with one-click alternatives. */}
        {!analyzing && !analyzeError && refused && (
          <Card className="p-4 md:p-5">
            <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
              <FlaskConical size={14} className="text-blue-700" /> No supported action
            </h3>
            <p className="mt-1.5 text-[12.5px] text-slate-700 leading-relaxed">
              {strOf(refusalObj?.headline || result?.reason || result?.detail || "Nothing in your data cleared the evidence bar for an intervention.")}
            </p>
            {refusalAlts.length > 0 && (
              <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                {refusalAlts.map((a: any, i: number) => (
                  <button
                    key={i}
                    onClick={() => {
                      const am = strOf(a?.metric);
                      const ad = strOf(a?.driver);
                      if (am) void runAnalyze({ metric: am, driver: ad });
                      else onGoto("explore");
                    }}
                    className="text-[11.5px] font-medium text-blue-700 border border-blue-200 rounded-full px-2.5 py-1 hover:bg-blue-50"
                    aria-label={`Re-run with ${strOf(a?.label || `${a?.metric} ${a?.driver}`)}`}
                  >
                    {strOf(a?.label || `${humanize(a?.driver)} for ${humanize(a?.metric)}`)}
                  </button>
                ))}
              </div>
            )}
            {refusalAlts.length === 0 && legacyAlts.length > 0 && (
              <div className="mt-2 flex items-center gap-1.5 flex-wrap">
                {legacyAlts.map((t: string, i: number) => (
                  <button
                    key={i}
                    onClick={() => {
                      const l = t.toLowerCase();
                      if (/hypothesis|investigat/.test(l)) onGoto("hypotheses");
                      else if (/what-?if|scenario/.test(l)) onGoto("whatif");
                      else if (/goal/.test(l)) onGoto("goals");
                      else onGoto("explore");
                    }}
                    className="text-[11.5px] font-medium text-blue-700 border border-blue-200 rounded-full px-2.5 py-1 hover:bg-blue-50"
                  >
                    {t}
                  </button>
                ))}
              </div>
            )}
            <p className="mt-2 text-[11px] text-slate-400">
              ARIA would rather refuse than invent an action — try another metric or driver.
            </p>
            {(() => {
              const tested = asList(result?.tested);
              if (!tested.length) return null;
              const tone = (v: string) =>
                v === "passed" ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                : v === "rejected" ? "text-slate-500 bg-slate-50 border-slate-200"
                : "text-amber-700 bg-amber-50 border-amber-200";
              return (
                <details className="mt-2 rounded-xl bg-slate-50 border border-slate-100 px-2.5 py-2">
                  <summary className="text-[11.5px] font-semibold text-blue-700 cursor-pointer hover:underline">
                    What was tested ({tested.length} driver{tested.length === 1 ? "" : "s"})
                  </summary>
                  <ul className="mt-1.5 space-y-1.5">
                    {tested.map((t: any, i: number) => (
                      <li key={i} className="flex items-start gap-2 text-[11.5px]">
                        <span className={`flex-shrink-0 font-semibold px-1.5 py-0.5 rounded border ${tone(strOf(t?.verdict))}`}>
                          {strOf(t?.verdict) || "checked"}
                        </span>
                        <span className="min-w-0">
                          <span className="font-medium text-[#0F2440]">{humanize(strOf(t?.driver))}</span>
                          {strOf(t?.note) && <span className="text-slate-500"> — {strOf(t.note)}</span>}
                        </span>
                      </li>
                    ))}
                  </ul>
                </details>
              );
            })()}
          </Card>
        )}

        {/* Results */}
        {!analyzing && !analyzeError && !refused && prescriptions.length > 0 && (
          <StaggerGroup className="space-y-4">
            <StaggerItem>
              <Card className="p-4 md:p-5">
                <div className="flex items-start justify-between gap-3 flex-wrap">
                  <div>
                    <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
                      <Sparkles size={14} className="text-blue-700" /> Recommended Actions
                    </h3>
                    <p className="text-[11px] text-slate-500 mt-0.5">{strOf(result?.story)}</p>
                  </div>
                  <StatPill tone="info">{prescriptions.length} recommendation{prescriptions.length === 1 ? "" : "s"}</StatPill>
                </div>
                <div className="mt-3 space-y-2.5">
                  {prescriptions.map((p: any, i: number) => {
                    const id = strOf(p?.id || `rx-${i}`);
                    const disp = dispOf(p);
                    const det = detailsOf(p);
                    const title = strOf(disp.title || p?.title || p?.name, `Recommendation ${i + 1}`);
                    const problem = problemOf(p);
                    const bullets = whyBulletsOf(p, 3);
                    const actionText = strOf(disp.action_text);
                    const outcomeText = strOf(disp.outcome_text);
                    const confTxt = strOf(disp.confidence_label || p?.confidence_label || p?.confidence) || "—";
                    const risk = strOf(p?.risk);
                    const evPass = det.evidence_pass;
                    const saved = savedIds.has(id) || savedIds.has(title);
                    const savingThis = savingId === id;
                    const impact = p?.impact && typeof p.impact === "object" ? p.impact : {};
                    const bl = numOf(impact.baseline);
                    const sc = numOf(impact.scenario);
                    const dl = numOf(impact.delta);
                    const relPct = numOf(impact.rel_pct);
                    const n = numOf(det?.numbers?.n || det?.numbers?.n_points);
                    const limitations = limsOf(p);
                    const honest = strOf(p?.impact_note || p?.impactNote);
                    const showChart = bl !== null && sc !== null;
                    return (
                      <div key={id} className="rounded-xl border border-slate-200/80 p-4 hover:border-blue-200 transition-colors">
                        {/* Header: Title + Confidence + Risk */}
                        <div className="flex items-start justify-between gap-2 flex-wrap">
                          <p className="text-[13px] font-semibold text-[#0F2440] leading-snug flex-1 min-w-[200px]">{title}</p>
                          <span className="flex items-center gap-2 flex-shrink-0">
                            <ConfidenceDots level={confTxt} />
                            {risk && <RiskBadge risk={risk} />}
                          </span>
                        </div>

                        {/* Problem */}
                        {problem && (
                          <p className="mt-2 text-[12.5px] text-slate-700 leading-relaxed">{problem}</p>
                        )}

                        {/* Why — always visible */}
                        {bullets.length > 0 && (
                          <div className="mt-2">
                            {bullets.map((b, j) => (
                              <p key={j} className="text-[12px] text-slate-600 leading-relaxed">• {b}</p>
                            ))}
                          </div>
                        )}

                        {/* Mini chart: baseline vs projected */}
                        {showChart && (
                          <MiniRxChart baseline={bl} scenario={sc} delta={dl} metric={result?.metric || metric} />
                        )}

                        {/* Action + Outcome — prominent */}
                        <div className="mt-3 rounded-lg bg-blue-50/60 border border-blue-100 px-3 py-2.5">
                          {actionText && (
                            <p className="text-[12.5px] font-semibold text-[#0F2440]">{actionText}</p>
                          )}
                          {outcomeText && (
                            <p className="mt-1 text-[12px] text-slate-700">
                              {dl !== null && relPct !== null ? (
                                <span className="font-medium">
                                  {dl >= 0 ? <TrendingUp size={12} className="inline mr-1 text-green-600" /> : <TrendingDown size={12} className="inline mr-1 text-red-600" />}
                                  {dl >= 0 ? "+" : ""}{relPct.toFixed(1)}% {dl >= 0 ? "lift" : "drop"} expected
                                </span>
                              ) : outcomeText}
                            </p>
                          )}
                        </div>

                        {/* Inline evidence summary — no drill-down needed */}
                        <div className="mt-2 flex items-center gap-3 flex-wrap text-[11px] text-slate-500">
                          {n !== null && <span className="flex items-center gap-1"><BarChart3 size={11} /> {Math.round(n).toLocaleString()} data points</span>}
                          {evPass === true && <span className="flex items-center gap-1 text-green-600"><ShieldCheck size={11} /> Evidence verified</span>}
                          {evPass === false && <span className="flex items-center gap-1 text-amber-600"><AlertTriangle size={11} /> Limited evidence</span>}
                          {limitations.length > 0 && (
                            <span className="text-slate-400" title={limitations.join("; ")}>
                              {limitations.length} limitation{limitations.length === 1 ? "" : "s"}
                            </span>
                          )}
                        </div>

                        {/* Honest caveat if present */}
                        {honest && (
                          <div className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-2.5 py-1.5">
                            <Info size={11} className="text-amber-500 flex-shrink-0 mt-px" />
                            <span>{honest}</span>
                          </div>
                        )}

                        {/* Actions */}
                        <div className="mt-2.5 flex items-center gap-2 flex-wrap">
                          <button
                            onClick={() => void saveRx(p)}
                            disabled={!!savingThis || saved}
                            className={btnGhost}
                            aria-label={saved ? `Saved: ${title}` : `Save recommendation: ${title}`}
                          >
                            <Bookmark size={13} /> {saved ? "Saved ✓" : savingThis ? "Saving…" : "Save"}
                          </button>
                          <button
                            onClick={() => setCaseRx(p)}
                            className="inline-flex items-center gap-1 text-[12px] font-semibold text-blue-700 hover:underline"
                            aria-label={`Open business case: ${title}`}
                          >
                            <Eye size={13} /> Full details
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
                {saveMsg && <p className="mt-2 text-[11px] text-slate-600" role="status">{saveMsg}</p>}
              </Card>
            </StaggerItem>

            {/* Scenario playground */}
            {scenarioCands.length > 0 && (
              <StaggerItem>
                <Card className="p-4 md:p-5">
                  <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
                    <SlidersHorizontal size={14} className="text-blue-700" /> Scenario Playground
                  </h3>
                  <p className="text-[11px] text-slate-500 mt-0.5">
                    Test a what-if adjustment on a modeled driver — read-only, your data never changes.
                  </p>
                  <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
                    <Field label="Scenario card" htmlFor="rx-scen">
                      <select id="rx-scen" value={strOf(selected?.id)} onChange={(e) => { setSelId(e.target.value); setScResult(null); setScError(""); }} className={selectCls} aria-label="Scenario card">
                        {scenarioCands.map((p: any) => (
                          <option key={strOf(p?.id)} value={strOf(p?.id)}>{strOf(p?.title)}</option>
                        ))}
                      </select>
                    </Field>
                    <div>
                      <label htmlFor="rx-pct" className="block text-[11px] font-medium text-slate-500 mb-1">
                        {supportRange
                          ? `Try a change (safe range ${supportRange.min}% to ${supportRange.max}% from your past data)`
                          : "Try a change (no safe range in your past data — enter a value to test)"}
                      </label>
                      {supportRange ? (
                        <div className="flex items-center gap-3">
                          <span className="text-[11px] text-slate-400 w-8 text-right tabular-nums">{supportRange.min}%</span>
                          <div className="relative flex-1 h-6 flex items-center">
                            <div className="absolute inset-x-0 h-[3px] bg-slate-200 rounded-full" />
                            <div
                              className="absolute h-[3px] bg-blue-500 rounded-full"
                              style={{
                                left: `${((Math.max(supportRange.min, Math.min(supportRange.max, pct)) - supportRange.min) / (supportRange.max - supportRange.min)) * 100}%`,
                                right: 0,
                              }}
                            />
                            <input
                              id="rx-pct" type="range" min={supportRange.min} max={supportRange.max} step={0.5} value={pct}
                              onChange={(e) => setPct(Number(e.target.value))}
                              className="absolute inset-0 w-full h-full opacity-0 cursor-pointer z-10"
                              aria-label="Adjustment percent slider"
                            />
                            <div
                              className="absolute w-4 h-4 bg-white border-2 border-blue-600 rounded-full shadow-sm pointer-events-none z-20 transition-transform hover:scale-110"
                              style={{
                                left: `calc(${((Math.max(supportRange.min, Math.min(supportRange.max, pct)) - supportRange.min) / (supportRange.max - supportRange.min)) * 100}% - 8px)`,
                              }}
                            />
                          </div>
                          <span className="text-[11px] text-slate-400 w-8 tabular-nums">{supportRange.max}%</span>
                          <span className="text-[13px] font-bold text-[#0F2440] tabular-nums w-14 text-right">{pct >= 0 ? "+" : ""}{pct}%</span>
                        </div>
                      ) : (
                        <input
                          id="rx-pct" type="number" step={0.5} value={pct}
                          onChange={(e) => setPct(Number(e.target.value) || 0)}
                          className={inputCls} aria-label="Adjustment percent"
                        />
                      )}
                    </div>
                  </div>
                  <div className="mt-3">
                    <button onClick={runScenario} disabled={scRunning || !selected} className={btnPrimary} aria-label="Run scenario">
                      {scRunning ? "Running…" : "Run Scenario"} <Play size={13} />
                    </button>
                  </div>
                  {scRunning && <LoadingPanel label="Recomputing scenario from your data…" />}
                  {!scRunning && scError && (
                    <div className="mt-3 rounded-xl border border-rose-100 bg-rose-50/50 p-3" role="alert">
                      <p className="text-[12px] text-rose-700">{scError}{scErrorId ? ` (Request ID: ${scErrorId})` : ""}</p>
                      <button onClick={runScenario} className="mt-1.5 inline-flex items-center gap-1.5 text-[12px] font-semibold text-blue-700 hover:underline" aria-label="Retry scenario">
                        <RefreshCw size={12} /> Retry
                      </button>
                    </div>
                  )}
                  {!scRunning && !scError && scFirst && (
                    <div className="mt-3 rounded-xl border border-slate-200/80 p-3">
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        {[
                          ["Baseline (observed)", scFirst.baseline],
                          ["Scenario (simulated)", scFirst.scenario],
                          [`Change (${pct >= 0 ? "+" : ""}${pct}%)`, scFirst.delta],
                        ].map(([label, v]: any) => (
                          <div key={label} className="rounded-lg bg-slate-50 border border-slate-100 px-3 py-2">
                            <p className="text-[11px] font-medium text-slate-500">{label}</p>
                            <p className="text-[18px] font-bold text-[#0F2440] tabular-nums">
                              {numOf(v) === null ? "—" : fmtMetric(numOf(v) as number, result?.metric)}
                            </p>
                          </div>
                        ))}
                      </div>
                      {numOf(scFirst.rel_pct) !== null && (
                        <p className="mt-2 text-[12px] text-slate-600">
                          Relative change: <span className="font-semibold tabular-nums">{(numOf(scFirst.rel_pct) as number) >= 0 ? "+" : ""}{(numOf(scFirst.rel_pct) as number).toFixed(1)}%</span>
                          {scFirst.in_historical_range === false && (
                            <span className="ml-2 text-amber-700">Outside the observed driver range — extrapolation, treat cautiously.</span>
                          )}
                        </p>
                      )}
                      {asList(scResult?.assumptions).length > 0 && (
                        <p className="mt-1.5 text-[11.5px] text-slate-500 leading-relaxed">
                          <span className="font-medium">Assumptions: </span>
                          {asList(scResult.assumptions).map((a: any) => strOf(typeof a === "string" ? a : a?.text)).filter(Boolean).join(" ")}
                        </p>
                      )}
                      {strOf(scResult?.warning) && (
                        <div className="mt-2 flex items-start gap-1.5 text-[11.5px] text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-2.5 py-2">
                          <Info size={13} className="text-amber-600 flex-shrink-0 mt-px" />
                          <span>{strOf(scResult.warning)}</span>
                        </div>
                      )}
                    </div>
                  )}
                </Card>
              </StaggerItem>
            )}
          </StaggerGroup>
        )}

        {/* First-visit empty state */}
        {!analyzing && !analyzeError && !result && !metric && (
          <EmptyState
            icon={ClipboardList}
            title="Pick a metric above to start"
            body="ARIA will test each driver against the evidence gates and either recommend with proof — or tell you honestly that nothing qualifies."
            action={<button onClick={loadCtx} className="text-xs font-semibold text-blue-700 hover:underline">Refresh options</button>}
          />
        )}
        {!analyzing && !analyzeError && !result && metric && (
          <EmptyState
            icon={ClipboardList}
            title={`Ready to analyze ${humanize(metric)}`}
            body="Click Run Analysis above, or pick a driver/segment to narrow the scope."
            action={<button onClick={() => void runAnalyze()} className="text-xs font-semibold text-blue-700 hover:underline">Run Analysis</button>}
          />
        )}

        {/* Saved */}
        <Card className="p-4 md:p-5">
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight flex items-center gap-1.5">
                <Bookmark size={14} className="text-blue-700" /> Saved Recommendations
              </h3>
              <p className="text-[11px] text-slate-500 mt-0.5">
                {savedServer !== null ? "Stored per-user on the server." : "Server list unavailable — showing items kept on this device."}
              </p>
            </div>
            <button onClick={loadSaved} className={btnGhost} aria-label="Refresh saved recommendations">
              <RefreshCw size={13} /> Refresh
            </button>
          </div>
          {savedCombined.length === 0 ? (
            <p className="mt-2 text-[12px] text-slate-400">Nothing saved yet — save a recommendation above and it will appear here.</p>
          ) : (
            <div className="mt-2 divide-y divide-slate-100">
              {savedCombined.map(({ item, local }: any, i: number) => {
                const sid = strOf(item?.id || item?.title || `saved-${i}`);
                const title = strOf(item?.title || item?.name || "Saved recommendation");
                return (
                  <div key={`${local ? "local" : "server"}-${sid}`} className="py-2 flex items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <p className="text-[12.5px] font-medium text-[#0F2440] truncate">{title}</p>
                      <p className="text-[11px] text-slate-400 truncate">
                        {strOf(item?.question || item?.summary || "")}{local ? " · kept on this device" : ""}
                      </p>
                    </div>
                    <button
                      onClick={() => setCaseRx(item)}
                      className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-blue-700 hover:underline flex-shrink-0"
                      aria-label={`Open business case: ${title}`}
                    >
                      <Eye size={12} /> Case
                    </button>
                    <button
                      onClick={() => void unsaveRx(sid, local)}
                      className="inline-flex items-center gap-1 text-[11.5px] font-medium text-slate-400 hover:text-rose-600 flex-shrink-0"
                      aria-label={`Remove saved recommendation: ${title}`}
                    >
                      <Trash2 size={12} /> Remove
                    </button>
                  </div>
                );
              })}
            </div>
          )}
          <div className="mt-3 pt-3 border-t border-slate-100 flex items-center gap-3 flex-wrap">
            <button onClick={() => onGoto("explore")} className="text-[11.5px] font-medium text-slate-500 hover:text-blue-700 hover:underline">
              ← Back to Explore
            </button>
            <button onClick={() => onAsk(`What should I consider for ${metric || "my key metric"}?`)} className="text-[11.5px] font-medium text-slate-500 hover:text-blue-700 hover:underline">
              Ask Copilot about this
            </button>
          </div>
        </Card>
        <RxCaseDrawer
          open={caseRx !== null}
          onClose={() => setCaseRx(null)}
          rx={caseRx}
          onAsk={onAsk}
          onUpdateSaved={updateSavedRx}
        />
      </div>
    </MotionConfig>
  );
}
