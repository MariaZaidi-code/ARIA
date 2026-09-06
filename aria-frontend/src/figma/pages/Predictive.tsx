import { useState } from "react";
import { TrendingUp, Settings2, ChevronDown, Info } from "lucide-react";
import { ComposedChart, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine } from "recharts";
import { useTheme } from "../App";

interface PredictiveProps {
  insightResult?: any;
  goalResult?: any;
}

export default function Predictive({ insightResult = null, goalResult = null }: PredictiveProps) {
  const { isDark } = useTheme();

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  // Extract predictions from insight result
  const predictions = insightResult?.predictions || {};
  const hasPredictions = predictions && (predictions.valid || predictions.points?.length > 0);

  // Show empty state if no predictions
  if (!hasPredictions) {
    return (
      <div className="p-6 max-w-screen-xl mx-auto">
        <div>
          <h2 className="text-xl font-semibold text-foreground tracking-tight">Predictive Analysis</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Understand what is likely to happen next.</p>
        </div>
        <div className="mt-8 text-center py-12 bg-card border border-border rounded-xl">
          <p className="text-muted-foreground">No predictions available yet.</p>
          <p className="text-xs text-muted-foreground mt-2">Run a time-series analysis to generate forecasts.</p>
        </div>
      </div>
    );
  }

  const forecastData = predictions.points || [];
  const method = predictions.method || "Auto-detected";
  const accuracy = predictions.accuracy_pct || null;
  const reliability = predictions.reliability || "medium";

  return (
    <div className="p-6 max-w-screen-xl mx-auto space-y-6">
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">Predictive Analysis</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Forecast based on {predictions.column || "historical data"}.</p>
      </div>

      {/* Accuracy Badge */}
      {accuracy && (
        <div className="premium-card bg-card border border-border rounded-xl p-5 cursor-default">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Forecast Quality</p>
              <div className="flex items-center gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Method</p>
                  <p className="text-base font-semibold text-foreground">{method}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Accuracy</p>
                  <p className="text-base font-semibold text-positive">{accuracy.toFixed(1)}%</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Reliability</p>
                  <p className={`text-base font-semibold capitalize ${
                    reliability === "high" ? "text-positive" :
                    reliability === "medium" ? "text-warning" : "text-muted-foreground"
                  }`}>{reliability}</p>
                </div>
              </div>
            </div>
            {predictions.valid && (
              <div className="flex items-center gap-2 text-sm text-positive">
                <div className="w-2 h-2 rounded-full bg-positive" />
                Validated
              </div>
            )}
          </div>
        </div>
      )}

      {/* Main chart */}
      <div className="bg-card border border-border rounded-xl p-5">
        <div className="flex items-center justify-between mb-5">
          <div>
            <p className="text-sm font-semibold text-foreground">{predictions.column || "Metric"} Forecast</p>
            <p className="text-xs text-muted-foreground mt-0.5">{forecastData.length} forecast points</p>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={320}>
          <ComposedChart data={forecastData}>
            <defs>
              <linearGradient id="confGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="var(--primary)" stopOpacity={0.1} />
                <stop offset="95%" stopColor="var(--primary)" stopOpacity={0.05} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} />
            <YAxis tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={60} />
            <Tooltip
              contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12, boxShadow: "var(--shadow-md)" }}
              labelStyle={{ color: "var(--foreground)", fontWeight: 600 }}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {predictions.lower95 && <Area type="monotone" dataKey="lower95" stroke="none" fill="url(#confGrad)" name="95% Range" />}
            {predictions.upper95 && <Area type="monotone" dataKey="upper95" stroke="none" fill="url(#confGrad)" />}
            <Line type="monotone" dataKey="actual" stroke="var(--foreground)" strokeWidth={2} dot={{ r: 3 }} name="Historical" />
            <Line type="monotone" dataKey="forecast" stroke="var(--primary)" strokeWidth={2} strokeDasharray="5 5" dot={{ r: 3 }} name="Forecast" />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Forecast summary */}
      {predictions.reason && (
        <div className="bg-card border border-border rounded-xl p-5">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Analysis Notes</p>
          <p className="text-sm text-foreground leading-relaxed">{predictions.reason}</p>
        </div>
      )}
    </div>
  );
}
