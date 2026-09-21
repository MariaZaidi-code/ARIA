/* Business-case drawer for one prescription: problem, why this is
   suggested, action, outcome (with modeled range bands + comparison
   chart, or an honest no-sized-outcome note when impact.delta is None),
   risks, review plan with tracker, business fields, HTML export. Every
   value comes from the live prescription payload — nothing invented.
   Statistic keys (r/p/slope) are never rendered raw — only plain labels
   (Link strength / Data points / Chance noise). */

import { useMemo, useState } from "react";
import { X, Download, Check, AlertTriangle, CalendarDays, User, Flag } from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, Cell,
} from "recharts";
import {
  asList, strOf, numOf, humanize, titleCase, fmtMetric,
} from "../../lib/intelHelpers";
import { prescriptionApi } from "../../../services/api";

export interface RxCaseDrawerProps {
  open: boolean;
  onClose: () => void;
  rx: any;
  onAsk?: (q: string) => void;
  onUpdateSaved?: (id: string, patch: Record<string, string>) => Promise<void>;
}

function money(v: any, metric: string): string {
  const n = numOf(v);
  if (n === null) return "—";
  return fmtMetric(n, metric);
}

export default function RxCaseDrawer({ open, onClose, rx, onAsk, onUpdateSaved }: RxCaseDrawerProps) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [owner, setOwner] = useState("");
  const [priority, setPriority] = useState("");
  const [due, setDue] = useState("");
  const [reviewNote, setReviewNote] = useState("");

  const metric = strOf(rx?.evidence?.metric || rx?.metric || "");
  const disp = (rx?.display && typeof rx.display === "object" ? rx.display : {}) as any;
  const impact = (rx?.impact && typeof rx.impact === "object" ? rx.impact : {}) as any;
  const options = asList(rx?.scenario_options);
  const lims = asList(rx?.limitations).map((l: any) => strOf(typeof l === "string" ? l : l?.text)).filter(Boolean);
  const assumptions = asList(rx?.assumptions).map((a: any) => strOf(typeof a === "string" ? a : a?.text)).filter(Boolean);
  const honest = strOf(rx?.impact_note || rx?.impactNote);
  const review = strOf(rx?.review_period || rx?.reviewPeriod);
  const reviewBasis = strOf(rx?.review_basis || rx?.reviewBasis);
  const success = (rx?.success_metric && typeof rx.success_metric === "object" ? rx.success_metric : {}) as any;
  const next = (rx?.recommended_next_analysis && typeof rx.recommended_next_analysis === "object" ? rx.recommended_next_analysis : {}) as any;

  const bands = useMemo(() => {
    const range = asList(impact?.range).map(numOf).filter((v): v is number => v !== null);
    const delta = numOf(impact?.delta);
    const base = numOf(impact?.baseline);
    const scen = numOf(impact?.scenario);
    const rel = numOf(impact?.rel_pct);
    return { range, delta, base, scen, rel };
  }, [rx]);

  /* Non-technical contract (new display fields first, legacy fallback):
     Problem <- display.problem_text (else summary_plain/story/summary);
     Why    <- display.why_text bullets via the api.js contract (else
               why_summary). Statistic keys never render raw — plain
     labels come from the same contract. */
  const rxApi: any = prescriptionApi as any;
  const problem: string = (() => {
    try {
      const v = strOf(rxApi.problemOf?.(rx));
      if (v) return v;
    } catch { /* fall through */ }
    return strOf(rx?.summary_plain || rx?.story || rx?.summary || disp.why_summary);
  })();
  const bullets: string[] = (() => {
    try {
      const v = rxApi.whyBulletsOf?.(rx, 3);
      if (Array.isArray(v)) return v.map((x) => strOf(x)).filter(Boolean).slice(0, 3);
    } catch { /* fall through */ }
    const legacy = strOf(disp.why_summary);
    return legacy ? [legacy] : [];
  })();
  const plainLabelOf = (key: string): string => {
    try {
      const v = strOf(rxApi.plainNumberLabel?.(key));
      if (v) return v;
    } catch { /* fall through */ }
    if (/^[a-z]$/i.test(String(key ?? "").trim())) return "Detail";
    return humanize(key);
  };
  const det = (rx?.details && typeof rx.details === "object" ? rx.details : {}) as any;
  const detNumbers: Record<string, unknown> = (() => {
    try {
      const n = rxApi.numbersOf?.(rx);
      if (n && typeof n === "object") return n as Record<string, unknown>;
    } catch { /* fall through */ }
    const raw = det.numbers;
    return raw && typeof raw === "object" ? raw : {};
  })();
  const numRows = Object.entries(detNumbers);
  const fmtNum = (key: string, v: unknown): string => {
    if (typeof v === "string") return v;
    const k = String(key || "").toLowerCase();
    if (k === "p_value" || k === "p") {
      try {
        const w = strOf(rxApi.chanceNoiseWords?.(v));
        if (w) return w;
      } catch { /* fall through to numeric */ }
    }
    const n = numOf(v);
    if (n === null) return strOf(v);
    if (k === "n" || k === "n_points") return Math.round(n).toLocaleString();
    if (k === "effect_r" || k === "r" || k === "spearman_r" || k === "slope") {
      return `${n >= 0 ? "+" : ""}${Math.round(n * 100) / 100}`;
    }
    if (["baseline", "scenario", "delta", "first", "last", "mean", "driver_value"].includes(k)) {
      return money(n, metric);
    }
    if (k.includes("pct") || k.includes("gap") || k.includes("share") || k.includes("momentum") || k === "rel_pct") {
      return `${n >= 0 ? "+" : ""}${Math.round(n * 10) / 10}%`;
    }
    return strOf(v);
  };
  /* No sized outcome when the engine left impact.delta empty: hide the
     Worst/Expected/Best boxes and say so honestly instead. */
  const hasSizedOutcome = bands.delta !== null;

  if (!open || !rx) return null;

  const esc = (s: any): string => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const exportHtml = () => {
    try {
      const rows = options.map((o: any) => `<tr><td>${esc(o?.label || o?.scenario_label || "")}</td><td>${esc(o?.baseline ?? "")}</td><td>${esc(o?.scenario ?? "")}</td><td>${esc(o?.delta ?? "")}</td><td>${esc(o?.rel_pct ?? "")}%</td></tr>`).join("");
      const html = `<!doctype html><html><head><meta charset="utf-8"><title>${esc(rx?.title || "Business case")}</title></head><body style="font-family:sans-serif;max-width:720px;margin:32px auto;color:#0F2440"><p style="color:#1d4ed8;font-weight:700;letter-spacing:2px">ARIA</p><h1>${esc(rx?.title || "Recommendation")}</h1>${problem ? `<h2>The problem</h2><p>${esc(problem)}</p>` : ""}<p>${esc(disp.action_text || rx?.summary || "")}</p><h2>Expected outcome</h2><p>${esc(disp.outcome_text || "")}</p>${options.length ? `<table border="1" cellpadding="6" cellspacing="0"><tr><th>Option</th><th>Baseline</th><th>Scenario</th><th>Delta</th><th>Change %</th></tr>${rows}</table>` : ""}${bullets.length ? `<h2>Why this is suggested</h2><ul>${bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}${honest ? `<p><em>${esc(honest)}</em></p>` : ""}<h2>Risks &amp; assumptions</h2><ul>${assumptions.map((a) => `<li>${esc(a)}</li>`).join("")}${lims.map((l) => `<li>${esc(l)}</li>`).join("")}</ul>${review ? `<h2>Review plan</h2><p>${esc(review)}${reviewBasis ? ` — ${esc(reviewBasis)}` : ""}</p>` : ""}<p style="color:#64748b;font-size:12px">Modeled estimate from your historical data. Actual results may vary.</p></body></html>`;
      const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `${String(rx?.title || "business-case").replace(/[^a-z0-9-_]+/gi, "-").toLowerCase()}.html`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch { /* best-effort */ }
  };

  const patchFields = async (patch: Record<string, string>) => {
    const id = strOf(rx?.id);
    if (!id || !onUpdateSaved) return;
    setBusy(true);
    setMsg("");
    try {
      await onUpdateSaved(id, patch);
      setMsg("Saved.");
    } catch (e: any) {
      setMsg(strOf(e?.message) || "Could not save.");
    } finally {
      setBusy(false);
    }
  };

  const setOutcome = (outcome: string) =>
    patchFields({ review_outcome: outcome, review_note: reviewNote || undefined as any, review_at: new Date().toISOString() } as any);

  const chartData = options.length
    ? options.slice(0, 3).map((o: any) => ({
        label: titleCase(strOf(o?.label || o?.scenario_label || "Option")),
        baseline: numOf(o?.baseline) ?? 0,
        scenario: numOf(o?.scenario) ?? 0,
      }))
    : (bands.base !== null && bands.scen !== null
        ? [{ label: "Outcome", baseline: bands.base, scenario: bands.scen }]
        : []);

  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Prescription business case">
      <div className="absolute inset-0 bg-slate-900/40" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full max-w-lg bg-white shadow-2xl flex flex-col">
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-slate-100">
          <div>
            <p className="text-[11px] font-bold tracking-[0.14em] text-blue-700">BUSINESS CASE</p>
            <h3 className="text-[15px] font-semibold text-[#0F2440] tracking-tight mt-0.5">{strOf(rx?.title || "Recommendation")}</h3>
          </div>
          <button onClick={onClose} className="inline-flex items-center justify-center w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-500" aria-label="Close business case"><X size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">The problem</h4>
            <p className="mt-1.5 text-[13px] text-slate-700 leading-relaxed">{problem || "See the evidence below."}</p>
          </section>
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">Why this is suggested</h4>
            {bullets.length > 0 ? (
              <ul className="mt-1.5 space-y-1">
                {bullets.map((b, i) => <li key={i} className="text-[13px] text-slate-700 leading-relaxed">• {b}</li>)}
              </ul>
            ) : (
              <p className="mt-1.5 text-[12.5px] text-slate-400">No plain-language reason was provided.</p>
            )}
            {numRows.length > 0 && (
              <details className="mt-2 rounded-xl bg-slate-50 border border-slate-100 px-2.5 py-2">
                <summary className="text-[11.5px] font-semibold text-blue-700 cursor-pointer hover:underline">
                  See the numbers
                </summary>
                <dl className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-1">
                  {numRows.map(([k, v]) => (
                    <div key={k} className="flex items-baseline justify-between gap-2 text-[11px]">
                      <dt className="text-slate-400 truncate">{plainLabelOf(k)}</dt>
                      <dd className="font-medium text-[#0F2440] tabular-nums text-right truncate">{fmtNum(k, v)}</dd>
                    </div>
                  ))}
                </dl>
              </details>
            )}
          </section>
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">Recommended action</h4>
            <p className="mt-1.5 text-[13.5px] font-semibold text-[#0F2440] leading-snug">{strOf(disp.action_text || rx?.title)}</p>
            {strOf(disp.outcome_text) && <p className="mt-1 text-[15px] font-bold text-blue-800 tabular-nums">{strOf(disp.outcome_text)}</p>}
          </section>
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">Expected outcome</h4>
            {!hasSizedOutcome ? (
              <div className="mt-2 rounded-xl bg-amber-50 border border-amber-200 px-3 py-2">
                <p className="text-[12.5px] text-amber-800 leading-relaxed">
                  {honest || strOf(disp.outcome_text) || "No sized outcome — this is guidance to review, not a forecast."}
                </p>
              </div>
            ) : (
              <div className="mt-2 grid grid-cols-3 gap-2">
                {[
                  ["Worst (modeled low)", bands.range.length ? bands.range[0] : null],
                  ["Expected", bands.delta],
                  ["Best (modeled high)", bands.range.length ? bands.range[bands.range.length - 1] : null],
                ].map(([label, v]: any) => (
                  <div key={label} className="rounded-xl bg-slate-50 border border-slate-100 px-3 py-2">
                    <p className="text-[10.5px] text-slate-500">{label}</p>
                    <p className="text-[15px] font-bold text-[#0F2440] tabular-nums">{v === null ? "—" : money(v, metric)}</p>
                  </div>
                ))}
              </div>
            )}
            {chartData.length > 0 && (
              <div className="h-44 mt-2" role="img" aria-label="Baseline versus scenario outcomes">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" vertical={false} />
                    <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: "#9CA3AF" }} axisLine={false} tickLine={false} width={56} tickFormatter={(v: number) => money(v, metric)} />
                    <Tooltip formatter={(v: any, name: any) => [money(v, metric), humanize(String(name))]} cursor={{ fill: "#EFF6FF" }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="baseline" name="Baseline (observed)" fill="#C7D6E8" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="scenario" name="Scenario (simulated)" fill="#4F46E5" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
            <p className="mt-1.5 text-[11px] text-slate-400">Modeled range from your historical data — estimates, not promises.</p>
          </section>
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">Risks &amp; assumptions</h4>
            <ul className="mt-1.5 space-y-1">
              {strOf(rx?.risk) && <li className="text-[12.5px] text-slate-600">• Risk: {titleCase(strOf(rx.risk))}.</li>}
              {assumptions.map((a, i) => <li key={i} className="text-[12.5px] text-slate-600">• {a}</li>)}
              {lims.map((l, i) => <li key={`l${i}`} className="text-[12.5px] text-slate-600">• {l}</li>)}
              {!assumptions.length && !lims.length && !strOf(rx?.risk) && <li className="text-[12.5px] text-slate-400">None recorded.</li>}
            </ul>
            {/* Shown here only when a sized outcome exists — otherwise the
               same note already appears under Expected outcome. */}
            {honest && hasSizedOutcome && (
              <div className="mt-2 flex items-start gap-1.5 text-[11.5px] text-amber-800 bg-amber-50 border border-amber-200 rounded-xl px-2.5 py-2">
                <AlertTriangle size={13} className="text-amber-600 flex-shrink-0 mt-px" /><span>{honest}</span>
              </div>
            )}
          </section>
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">Review plan</h4>
            {(review || reviewBasis || success?.metric) ? (
              <div className="mt-1.5 text-[12.5px] text-slate-600 space-y-1">
                {review && <p className="flex items-center gap-1.5"><CalendarDays size={13} className="text-slate-400" /> Review {review}{reviewBasis ? ` — ${reviewBasis}` : ""}</p>}
                {success?.metric && <p>Success looks like: {humanize(strOf(success.metric))} moving {strOf(success.direction || "")}{success.target_pct !== undefined && success.target_pct !== null ? ` by ${success.target_pct}%` : ""}.</p>}
              </div>
            ) : <p className="mt-1.5 text-[12.5px] text-slate-400">No review schedule recorded.</p>}
            <div className="mt-2 flex items-center gap-2 flex-wrap">
              {(["achieved", "missed", "inconclusive"] as const).map((o) => (
                <button key={o} disabled={busy || !strOf(rx?.id)} onClick={() => void setOutcome(o)} className={`text-[11.5px] font-semibold px-2.5 py-1.5 rounded-lg border transition-colors disabled:opacity-40 ${strOf(rx?.review_outcome).toLowerCase() === o ? "border-blue-600 bg-blue-50 text-blue-800" : "border-slate-200 text-slate-600 hover:border-blue-300 hover:text-blue-700"}`} aria-label={`Mark review ${o}`}>
                  {o === "achieved" ? "✓ " : ""}{titleCase(o)}
                </button>
              ))}
            </div>
            <input value={reviewNote} onChange={(e) => setReviewNote(e.target.value)} placeholder="Review note (optional)" className="mt-2 w-full bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-[12px]" aria-label="Review note" />
            {msg && <p className="mt-1.5 text-[11.5px] text-slate-600" role="status">{msg}</p>}
          </section>
          <section>
            <h4 className="text-[12px] font-semibold text-slate-500 uppercase tracking-wide">Ownership</h4>
            <div className="mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2">
              <label className="text-[11px] text-slate-500">Owner
                <span className="mt-0.5 flex items-center gap-1.5 rounded-lg border border-slate-200 px-2 py-1.5 bg-white"><User size={12} className="text-slate-400" />
                <input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder={strOf(rx?.owner) || "Unassigned"} className="w-full bg-transparent outline-none text-[12px] text-[#0F2440]" aria-label="Owner" /></span>
              </label>
              <label className="text-[11px] text-slate-500">Priority
                <span className="mt-0.5 flex items-center gap-1.5 rounded-lg border border-slate-200 px-2 py-1.5 bg-white"><Flag size={12} className="text-slate-400" />
                <select value={priority} onChange={(e) => setPriority(e.target.value)} className="w-full bg-transparent outline-none text-[12px] text-[#0F2440]" aria-label="Priority">
                  <option value="">{strOf(rx?.priority) ? titleCase(strOf(rx.priority)) : "Set…"}</option>
                  {["low", "medium", "high", "critical"].map((p) => <option key={p} value={p}>{titleCase(p)}</option>)}
                </select></span>
              </label>
              <label className="text-[11px] text-slate-500">Due
                <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="mt-0.5 w-full rounded-lg border border-slate-200 px-2 py-1.5 text-[12px] text-[#0F2440] bg-white" aria-label="Due date" />
              </label>
            </div>
            <button disabled={busy || !strOf(rx?.id) || (!owner && !priority && !due)} onClick={() => void patchFields(Object.fromEntries(Object.entries({ owner, priority, due }).filter(([, v]) => v)))} className="mt-2 inline-flex items-center gap-1.5 text-[12px] font-semibold text-blue-700 border border-blue-200 rounded-lg px-3 py-1.5 hover:bg-blue-50 disabled:opacity-40" aria-label="Save ownership">
              <Check size={13} /> Save ownership
            </button>
          </section>
          <section className="flex items-center gap-2 flex-wrap pb-2">
            <button onClick={exportHtml} className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-blue-700 border border-blue-200 rounded-lg px-3 py-2 hover:bg-blue-50" aria-label="Download business case HTML"><Download size={13} /> Download case</button>
            {strOf(next?.label) && onAsk && (
              <button onClick={() => onAsk(`Validate this recommendation: ${strOf(rx?.title)}`)} className="inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-500 hover:text-blue-700 hover:underline" aria-label="Ask ARIA to validate">Ask ARIA to validate</button>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}
