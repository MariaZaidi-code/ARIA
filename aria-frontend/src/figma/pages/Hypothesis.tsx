import { useState, useEffect } from "react";
import { FlaskConical, ChevronDown, Loader2, CheckCircle, XCircle } from "lucide-react";
import { ScatterChart, Scatter, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { useTheme } from "../App";

type HypStatus = "idle" | "running" | "done" | "error";

const exampleHypotheses = [
  "Is there a correlation between two numeric measures in the data?",
  "Do higher quantities correlate with higher total values?",
  "Is there a relationship between price and quantity?",
  "Are there patterns between different numeric columns?",
];

interface Props {
  insightResult?: any;
}

export default function Hypothesis({ insightResult }: Props) {
  const { isDark } = useTheme();
  const [hypothesis, setHypothesis] = useState("");
  const [status, setStatus] = useState<HypStatus>("idle");
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");
  const [dbName, setDbName] = useState("Connected Data");

  useEffect(() => {
    const token = localStorage.getItem("aria_auth_token");
    if (token) {
      fetch("/api/session/status", { headers: { Authorization: `Bearer ${token}` } })
        .then(r => r.json())
        .then(d => { if (d.db_name) setDbName(d.db_name); })
        .catch(() => {});
    }
  }, []);

  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";

  const runHypothesis = async (h?: string) => {
    const text = h || hypothesis;
    if (!text.trim()) return;
    setHypothesis(text);
    setStatus("running");
    setError("");
    setResult(null);

    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/hypothesis", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          hypothesis: text,
          dataset: dbName,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Hypothesis test failed");
      }

      setResult(data);
      setStatus("done");
    } catch (err: any) {
      setError(err?.message || "Failed to run hypothesis test");
      setStatus("error");
    }
  };

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-6">
      <div className="animate-fade-in">
        <h2 className="text-xl font-bold text-foreground tracking-tight">Hypothesis</h2>
        <p className="text-sm text-muted-foreground mt-0.5">Test assumptions against your data.</p>
      </div>

      <div className="bg-card border border-border rounded-xl p-5 space-y-4">
        <div className="flex items-start gap-3">
          <FlaskConical size={16} className="text-primary mt-0.5 flex-shrink-0" />
          <textarea
            value={hypothesis}
            onChange={(e) => setHypothesis(e.target.value)}
            placeholder="Does increasing discounts increase sales?"
            rows={2}
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none resize-none"
          />
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <span className="font-medium">Dataset:</span>
          <span className="px-2 py-0.5 bg-secondary border border-border rounded-md text-foreground">{dbName}</span>
        </div>

        <div className="flex gap-2">
          <button onClick={() => runHypothesis()} disabled={status === "running"}
            className="premium-btn btn-glow px-5 py-2 rounded-lg text-sm font-semibold text-white transition-all disabled:opacity-50"
            style={{ background: 'var(--gradient-primary)' }}>
            {status === "running" ? "Testing..." : "Test Hypothesis"}
          </button>
          <button onClick={() => { setHypothesis(""); setStatus("idle"); setResult(null); setError(""); }}
            className="premium-btn bg-secondary text-secondary-foreground px-4 py-2 rounded-lg text-sm font-medium hover:opacity-80 transition-opacity border border-border">
            Clear
          </button>
        </div>
      </div>

      {status === "idle" && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Try an example</p>
          <div className="flex flex-wrap gap-2">
            {exampleHypotheses.map((h) => (
              <button key={h} onClick={() => runHypothesis(h)}
                className="text-xs px-3 py-1.5 bg-card border border-border rounded-full text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors">
                {h}
              </button>
            ))}
          </div>
        </div>
      )}

      {status === "running" && (
        <div className="bg-card border border-border rounded-xl p-6 flex flex-col items-center gap-5">
          <Loader2 size={24} className="text-primary animate-spin" />
          <p className="text-sm text-muted-foreground">Running statistical test...</p>
        </div>
      )}

      {status === "error" && (
        <div className="bg-negative/10 border border-negative/20 rounded-xl p-5">
          <p className="text-sm text-negative font-medium">{error}</p>
        </div>
      )}

      {status === "done" && result && (
        <div className="space-y-4">
          <div className={`rounded-xl p-5 flex items-start gap-4 ${
            result.supported ? "bg-positive/5 border border-positive/30" : "bg-negative/5 border border-negative/30"
          }`}>
            {result.supported ? (
              <CheckCircle size={22} className="text-positive flex-shrink-0 mt-0.5" />
            ) : (
              <XCircle size={22} className="text-negative flex-shrink-0 mt-0.5" />
            )}
            <div className="space-y-1">
              <p className={`text-sm font-bold ${result.supported ? "text-positive" : "text-negative"}`}>
                {result.supported ? "Hypothesis Supported" : "Hypothesis Not Supported"}
              </p>
              <p className="text-sm text-foreground leading-relaxed">{result.interpretation}</p>
            </div>
          </div>

          {result.stats && (
            <div className="bg-card border border-border rounded-xl p-5 space-y-4">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Statistical Results</p>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                {Object.entries(result.stats).map(([key, value]) => (
                  <div key={key} className="space-y-0.5">
                    <p className="text-xs text-muted-foreground">{key}</p>
                    <p className="text-sm font-semibold text-foreground">{String(value)}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {result.scatter_data && result.scatter_data.length > 0 && (
            <div className="bg-card border border-border rounded-xl p-5">
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-4">Data Visualization</p>
              <ResponsiveContainer width="100%" height={220}>
                <ScatterChart>
                  <CartesianGrid strokeDasharray="3 3" stroke={grid} />
                  <XAxis dataKey="x" name={result.x_label || "X"} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false}
                    label={{ value: result.x_label || "X", position: "insideBottom", offset: -5, fontSize: 11, fill: axis }} />
                  <YAxis dataKey="y" name={result.y_label || "Y"} tick={{ fontSize: 11, fill: axis }} axisLine={false} tickLine={false} width={52} />
                  <Tooltip
                    contentStyle={{ background: "var(--card)", border: "1px solid var(--border)", borderRadius: 10, fontSize: 12 }}
                  />
                  <Scatter data={result.scatter_data} fill="var(--primary)" fillOpacity={0.6} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
