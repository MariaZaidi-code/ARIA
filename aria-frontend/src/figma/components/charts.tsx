import { useState } from "react";
import type { ReactNode } from "react";
import { fmtBiz } from "../lib/format";

/* =====================================================================
   Shared chart library (s.txt §§7–10, §17): ONE reusable pattern.
   - selectChart: intent + data shape -> chart type (never hardcoded per page)
   - ChartFrame: business title + explanation + empty/loading/error states
   - BizTooltip: Period / Metric / Value labels, human-scale numbers
   - BusinessMetric, ConfidenceIndicator: compact consistent facts
   - ToggleLegend: click series on/off (recharts `hide` wiring)
   ===================================================================== */

export type ChartIntent =
  | "trend"
  | "forecast"
  | "comparison"
  | "ranking"
  | "composition"
  | "relationship"
  | "distribution";

export interface DataShape {
  points: number;
  series: number;
  hasTime: boolean;
  categories: number;
}

export type ChartType =
  | "line"
  | "area"
  | "bar"
  | "hbar"
  | "stacked"
  | "pie"
  | "scatter"
  | "histogram"
  | "table";

export function selectChart(
  intent: ChartIntent,
  shape: DataShape,
): { type: ChartType; reason: string } {
  if (shape.points < 2) {
    return { type: "table", reason: "too few points to draw — table instead" };
  }
  switch (intent) {
    case "forecast":
      return { type: "line", reason: "history then forecast read left to right" };
    case "trend":
      return shape.series > 1
        ? { type: "line", reason: "several series over time" }
        : { type: "line", reason: "movement over time" };
    case "relationship":
      return shape.series >= 1 && !shape.hasTime
        ? { type: "scatter", reason: "two numbers against each other" }
        : { type: "line", reason: "relationship along time" };
    case "distribution":
      return { type: "histogram", reason: "spread of one number" };
    case "composition":
      return shape.categories <= 6
        ? { type: "pie", reason: "few parts of a whole" }
        : { type: "stacked", reason: "too many parts for a pie" };
    case "ranking":
      return shape.categories > 8
        ? { type: "hbar", reason: "many names read best sideways" }
        : { type: "bar", reason: "ranked comparison" };
    case "comparison":
    default:
      return shape.categories > 8
        ? { type: "hbar", reason: "many names read best sideways" }
        : { type: "bar", reason: "categories side by side" };
  }
}

/* ---------- human-scale numbers live in lib/format (single source) ---------- */

/** Short period labels: 2026-08-14 -> Aug 14, 2026-08 -> Aug 2026. */
export function fmtPeriod(label: string): string {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?/.exec(String(label || ""));
  if (!m) return String(label || "");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const mon = months[Number(m[2]) - 1] || m[2];
  return m[3] ? `${mon} ${Number(m[3])}, ${m[1]}` : `${mon} ${m[1]}`;
}

/* ---------- frame: title + explanation + states (§10) ---------- */

export function ChartFrame({
  title,
  explanation,
  empty,
  emptyText = "Not enough data to draw this chart.",
  loading,
  loadingText = "Preparing chart…",
  error,
  height = 260,
  children,
}: {
  title: string;
  explanation?: string;
  empty?: boolean;
  emptyText?: string;
  loading?: boolean;
  loadingText?: string;
  error?: string;
  height?: number;
  children: ReactNode;
}) {
  return (
    <div>
      <p className="text-[13px] font-semibold text-foreground">{title}</p>
      {explanation && (
        <p className="text-[11px] text-muted-foreground mt-0.5">{explanation}</p>
      )}
      <div className="mt-2" style={{ height }}>
        {loading ? (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground">
            {loadingText}
          </div>
        ) : error ? (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground px-4 text-center">
            Chart unavailable ({error}). The written explanation above still stands.
          </div>
        ) : empty ? (
          <div className="h-full flex items-center justify-center text-xs text-muted-foreground px-4 text-center">
            {emptyText}
          </div>
        ) : (
          children
        )}
      </div>
    </div>
  );
}

/* ---------- business tooltip: Period / Metric / Value (§7) ---------- */

export function BizTooltip({
  active,
  payload,
  label,
  periodLabel,
  metricNames,
}: {
  active?: boolean;
  payload?: any[];
  label?: string;
  periodLabel?: string;
  metricNames?: Record<string, string>;
}) {
  if (!active || !payload?.length) return null;
  const nameOf = (key: string) =>
    metricNames?.[key] || String(key).replace(/_/g, " ");
  return (
    <div
      className="rounded-lg border border-border px-3 py-2 shadow-md"
      style={{ background: "var(--card)" }}
    >
      {(periodLabel || label) && (
        <p className="text-[11px] font-bold text-foreground mb-1">
          {fmtPeriod(periodLabel ?? String(label ?? ""))}
        </p>
      )}
      {payload.map((p: any, i: number) => {
        const key = String(p.dataKey ?? p.name ?? "");
        const raw = p.value;
        const val =
          typeof raw === "number" ? fmtBiz(raw) : String(raw ?? "—");
        return (
          <p key={i} className="text-[11px] text-muted-foreground">
            <span
              className="inline-block w-2 h-2 rounded-full mr-1.5"
              style={{ background: p.color || p.payload?.fill || "var(--primary)" }}
            />
            {nameOf(key)}:{" "}
            <span className="text-foreground font-semibold">{val}</span>
          </p>
        );
      })}
    </div>
  );
}

export const tooltipStyle = {
  background: "var(--card)",
  border: "1px solid var(--border)",
  borderRadius: 10,
  fontSize: 12,
};

/* ---------- compact facts ---------- */

export function BusinessMetric({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div className="rounded-lg border border-border px-2.5 py-2">
      <p className="text-[10px] text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-sm font-bold text-foreground mt-0.5">{value}</p>
      {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
    </div>
  );
}

export function ConfidenceIndicator({
  level,
}: {
  level: string;
}) {
  const l = (level || "").toLowerCase();
  const dots = l === "high" ? 3 : l === "moderate" ? 2 : l === "low" ? 1 : 0;
  const tone =
    l === "high" ? "text-positive" : l === "moderate" ? "text-primary" : "text-warning";
  const label = l ? l[0].toUpperCase() + l.slice(1) : "Unknown";
  return (
    <span className="inline-flex items-center gap-1.5" title={`Confidence: ${label}`}>
      <span className="flex items-center gap-0.5" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className={`w-1.5 h-1.5 rounded-full ${i < dots ? "bg-positive" : "bg-border"}`}
          />
        ))}
      </span>
      <span className={`text-[10px] font-medium ${tone}`}>{label}</span>
    </span>
  );
}

/* ---------- series toggle (§7: toggle relevant series) ---------- */

export function useSeriesToggle(series: string[]) {
  const [hidden, setHidden] = useState<string[]>([]);
  return {
    hidden,
    toggle: (s: string) =>
      setHidden((h) => (h.includes(s) ? h.filter((x) => x !== s) : [...h, s])),
    isHidden: (s: string) => hidden.includes(s),
    reset: () => setHidden([]),
    count: series.length,
  };
}

export function ToggleLegend({
  items,
  isHidden,
  onToggle,
  colors,
}: {
  items: string[];
  isHidden: (s: string) => boolean;
  onToggle: (s: string) => void;
  colors: Record<string, string>;
}) {
  if (items.length < 2) return null;
  return (
    <div className="flex flex-wrap gap-3 mt-1">
      {items.map((s) => {
        const off = isHidden(s);
        return (
          <button
            key={s}
            onClick={() => onToggle(s)}
            className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
            aria-pressed={!off}
            title={off ? `Show ${s}` : `Hide ${s}`}
          >
            <span
              className="inline-block w-4 border-t-2"
              style={{
                borderColor: off ? "var(--border)" : colors[s] || "var(--primary)",
              }}
            />
            <span className={off ? "line-through opacity-60" : ""}>{s}</span>
          </button>
        );
      })}
    </div>
  );
}
