/* Shared Intelligence UI atoms (single source — Intelligence.tsx and
   intelligence/* import from here instead of duplicating markup).
   Presentation only: every value rendered through these atoms comes from a
   backend result. Light theme + existing Tailwind tokens; no new palette. */

import { useEffect, useRef, useState } from "react";
import { motion, type Variants } from "framer-motion";
import { AlertTriangle, Database, RefreshCw, Sparkles } from "lucide-react";
import { businessError } from "../../lib/intelHelpers";

/* ---------- motion presets (fade/slide + stagger; reduced-motion
   honored globally via MotionConfig reducedMotion="user") ---------- */

export const staggerParent: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.04 } },
};

export const fadeUp: Variants = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: "easeOut" } },
};

export function StaggerGroup({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div
      className={className}
      variants={staggerParent}
      initial="hidden"
      animate="show"
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <motion.div className={className} variants={fadeUp}>
      {children}
    </motion.div>
  );
}

/* ---------- number count-up (rAF-based, respects reduced-motion) ---------- */

export function useCountUp(target: number | null | undefined, duration = 650): number | null {
  const [value, setValue] = useState<number | null>(null);
  const fromRef = useRef(0);
  const rafRef = useRef(0);

  useEffect(() => {
    if (target === null || target === undefined || isNaN(Number(target))) {
      setValue(null);
      return;
    }
    const to = Number(target);
    let reduced = false;
    try {
      reduced =
        typeof window !== "undefined" &&
        !!window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
      reduced = false;
    }
    if (reduced || duration <= 0) {
      fromRef.current = to;
      setValue(to);
      return;
    }
    const from = fromRef.current;
    if (from === to) {
      setValue(to);
      return;
    }
    const t0 =
      typeof performance !== "undefined" && performance.now ? performance.now() : Date.now();
    const tick = (t: number) => {
      const p = Math.min(1, (t - t0) / duration);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = from + (to - from) * eased;
      setValue(v);
      if (p < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = to;
      }
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(rafRef.current);
      fromRef.current = to;
    };
  }, [target, duration]);

  return value;
}

/* Animated figure: animates toward the backend value; the displayed number
   is always the live backend figure once the glide settles. */
export function CountUp({
  value,
  format,
  className = "",
}: {
  value: number | null | undefined;
  format: (n: number) => string;
  className?: string;
}) {
  const animated = useCountUp(value);
  if (value === null || value === undefined || animated === null) {
    return <span className={className}>—</span>;
  }
  return <span className={className}>{format(animated)}</span>;
}

/* ---------- cards ---------- */

export function Card({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`bg-white border border-slate-200/80 rounded-2xl shadow-[0_1px_2px_rgba(15,36,64,0.05)] ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHead({
  title,
  sub,
  right,
}: {
  title: string;
  sub?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 flex-wrap px-4 pt-4 md:px-5">
      <div className="min-w-0">
        <h3 className="text-[14px] font-semibold text-[#0F2440] tracking-tight">{title}</h3>
        {sub && <p className="text-[11px] text-slate-500 mt-0.5">{sub}</p>}
      </div>
      {right}
    </div>
  );
}

/* Small status/range pill: tones reuse the existing slate/blue/emerald/rose
   Tailwind tokens — no new color system. */
export function StatPill({
  tone = "neutral",
  children,
  className = "",
  title,
}: {
  tone?: "neutral" | "info" | "up" | "down" | "warn";
  children: React.ReactNode;
  className?: string;
  title?: string;
}) {
  const tones: Record<string, string> = {
    neutral: "bg-slate-50 text-slate-600 border-slate-200",
    info: "bg-blue-50 text-blue-800 border-blue-100",
    up: "bg-emerald-50 text-emerald-700 border-emerald-200",
    down: "bg-rose-50 text-rose-700 border-rose-200",
    warn: "bg-amber-50 text-amber-700 border-amber-200",
  };
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 text-[11px] font-medium border rounded-full px-2.5 py-1 ${tones[tone]} ${className}`}
    >
      {children}
    </span>
  );
}

/* ---------- loading / error / empty ---------- */

export function SkeletonBlock({
  lines = 3,
  className = "",
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={`p-4 space-y-2 ${className}`} aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="skeleton h-3.5 rounded" style={{ width: `${92 - i * 14}%` }} />
      ))}
      <div className="skeleton h-28 rounded-xl" />
    </div>
  );
}

export function LoadingPanel({ label }: { label: string }) {
  return (
    <div aria-busy="true" aria-label={label}>
      <p className="sr-only">{label}</p>
      <Card>
        <SkeletonBlock lines={3} />
      </Card>
    </div>
  );
}

export function ErrorPanel({
  message,
  requestId,
  onRetry,
  retryLabel = "Retry",
}: {
  message: string;
  requestId?: string;
  onRetry: () => void;
  retryLabel?: string;
}) {
  return (
    <div
      className="bg-white border border-slate-200 rounded-2xl p-5 flex gap-3 shadow-sm"
      role="alert"
    >
      <AlertTriangle size={18} className="text-rose-500 flex-shrink-0 mt-0.5" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-[#0F2440]">ARIA couldn&apos;t load this section.</p>
        <p className="text-xs text-slate-500 mt-1">
          {businessError(message) || "Something went wrong on this request."}
        </p>
        {requestId && (
          <p className="text-[11px] text-slate-400 mt-1 font-mono">Request ID: {requestId}</p>
        )}
        <button
          onClick={onRetry}
          className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
        >
          <RefreshCw size={12} /> {retryLabel}
        </button>
      </div>
    </div>
  );
}

export function EmptyState({
  icon: Icon,
  title,
  body,
  action,
}: {
  icon?: React.ElementType;
  title: string;
  body: string;
  action?: React.ReactNode;
}) {
  const I = Icon || Sparkles;
  return (
    <div className="text-center py-10 bg-white border border-slate-200 rounded-2xl shadow-sm px-6">
      <I size={22} className="mx-auto text-slate-400 mb-3" />
      <p className="text-sm font-medium text-[#0F2440]">{title}</p>
      <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">{body}</p>
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

/* Back-compat alias for existing tab code. */
export const EmptyPanel = EmptyState;

function goData() {
  try {
    window.location.hash = "#/data";
  } catch {
    /* ignore */
  }
}

export function NoDatasetPanel({ onRetry, hint }: { onRetry?: () => void; hint?: string }) {
  return (
    <div className="text-center py-10 bg-white border border-slate-200 rounded-2xl shadow-sm px-6">
      <Database size={22} className="mx-auto text-slate-400 mb-3" />
      <p className="text-sm font-medium text-[#0F2440]">No data source connected</p>
      <p className="text-xs text-slate-500 mt-1 max-w-md mx-auto leading-relaxed">
        {hint ||
          "Connect PostgreSQL, MySQL, or upload a CSV on the Data page — then every section here will populate and Run Analysis will generate results."}
      </p>
      <div className="mt-3 flex items-center justify-center gap-2">
        <button
          onClick={goData}
          className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-[12.5px] font-semibold text-white bg-blue-700 hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          aria-label="Go to Data page"
        >
          Go to Data
        </button>
        {onRetry && (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:border-slate-300 bg-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label="Retry loading options"
          >
            <RefreshCw size={12} /> Retry
          </button>
        )}
      </div>
    </div>
  );
}

/* Lightweight SVG sparkline (no chart lib overhead): renders the trend array
   from the backend rows contract. */
export function Sparkline({
  values,
  width = 80,
  height = 28,
  color = "#2F6FAD",
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
}) {
  if (!values || values.length < 2) return <span className="text-slate-300">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const pts = values
    .map((v, i) => {
      const x = i * stepX;
      const y = height - 3 - ((v - min) / span) * (height - 6);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const lastX = width;
  const lastY = height - 3 - ((values[values.length - 1] - min) / span) * (height - 6);
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
      className="inline-block"
    >
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={lastX - 1} cy={lastY} r="2" fill={color} />
    </svg>
  );
}

/* ---------- form atoms (shared builder styling) ---------- */

export function Field({
  label,
  children,
  htmlFor,
}: {
  label: string;
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <label htmlFor={htmlFor} className="block min-w-0">
      <span className="block text-[11px] font-medium text-slate-500 mb-1">{label}</span>
      {children}
    </label>
  );
}

export const selectCls =
  "w-full bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-[12.5px] text-[#0F2440] focus:border-blue-500 outline-none cursor-pointer min-w-0";
export const inputCls =
  "w-full bg-white border border-slate-200 rounded-lg px-2.5 py-2 text-[12.5px] text-[#0F2440] placeholder:text-slate-400 focus:border-blue-500 outline-none min-w-0";
export const btnPrimary =
  "inline-flex items-center justify-center gap-1.5 px-4 py-2 rounded-lg text-[12.5px] font-semibold text-white bg-blue-700 hover:bg-blue-800 disabled:opacity-50 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1";
export const btnGhost =
  "inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-[12.5px] font-medium text-slate-600 border border-slate-200 hover:text-[#0F2440] hover:border-slate-300 bg-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500";
