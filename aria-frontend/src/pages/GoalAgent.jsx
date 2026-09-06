import { useState } from "react";
import { Target, Send, Loader2, AlertCircle, CheckCircle2 } from "lucide-react";
import "../goal-agent.css";

function GoalAgent({
  connectionStatus,
  onAnalyze,
  goalStatus,
  goalResult,
  insightResult,
}) {
  const [question, setQuestion] = useState("");
  const isConnected = connectionStatus === "connected";
  const isRunning = goalStatus === "running";
  const isSuccess = goalStatus === "success";
  const isFailed = goalStatus === "failed";

  const handleSubmit = () => {
    if (!question.trim() || isRunning) return;
    if (onAnalyze) {
      onAnalyze(question);
    }
  };

  const suggestions = [
    "What are the most important metrics for customer demographics?",
    "Which products generate the highest revenue?",
    "What are the monthly sales trends?",
    "Which customers are at risk of churning?",
  ];

  return (
    <div className="page-enter" style={{ maxWidth: 800, margin: "0 auto", padding: "32px 24px" }}>
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <Target size={24} style={{ color: "var(--aria-accent)" }} />
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Goal Agent</h1>
        </div>
        <p style={{ margin: 0, color: "var(--aria-text-muted)", fontSize: 14 }}>
          State a business goal or question and ARIA will analyze your data to find answers.
        </p>
      </div>

      <div className="section-card">
        <label style={{ display: "block", fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
          Business Question
        </label>
        <div className="goal-agent-input-row">
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") handleSubmit(); }}
            placeholder={isConnected ? "e.g., How can I increase monthly revenue?" : "Connect a data source first"}
            disabled={!isConnected || isRunning}
          />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={!isConnected || isRunning || !question.trim()}
          >
            {isRunning ? <Loader2 size={16} className="spin" /> : <Send size={16} />}
            {isRunning ? "Analyzing..." : "Ask ARIA"}
          </button>
        </div>

        {!isConnected && (
          <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--aria-warning)" }}>
            Please connect a data source before asking a question.
          </p>
        )}
      </div>

      <div style={{ marginBottom: 24 }}>
        <p style={{ fontSize: 12, fontWeight: 600, color: "var(--aria-text-subtle)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 8 }}>
          Suggested Questions
        </p>
        <div className="goal-suggestions">
          {suggestions.map((s) => (
            <button
              key={s}
              type="button"
              className="goal-suggestion-btn"
              onClick={() => { setQuestion(s); }}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {isFailed && (
        <div style={{
          padding: 16,
          borderRadius: 10,
          background: "var(--aria-error-light)",
          border: "1px solid var(--aria-error)",
          marginBottom: 24,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
            <AlertCircle size={16} style={{ color: "var(--aria-error)" }} />
            <strong style={{ color: "var(--aria-error)", fontSize: 14 }}>Analysis Failed</strong>
          </div>
          <p style={{ margin: 0, fontSize: 13, color: "var(--aria-text-muted)" }}>
            ARIA could not process this question. Please try again.
          </p>
        </div>
      )}

      {isSuccess && goalResult && (
        <div style={{
          background: "var(--aria-bg-elevated)",
          border: "1px solid var(--aria-border)",
          borderRadius: 12,
          padding: 24,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 16 }}>
            <CheckCircle2 size={18} style={{ color: "var(--aria-success)" }} />
            <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Analysis Complete</h3>
          </div>

          <div style={{ marginBottom: 16 }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: "var(--aria-text-subtle)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
              Question
            </p>
            <p style={{ margin: 0, fontSize: 14 }}>{goalResult.interpretedGoal}</p>
          </div>

          {goalResult.clarificationRequired && (
            <div style={{
              padding: 12,
              borderRadius: 8,
              background: "var(--aria-warning-light)",
              marginBottom: 16,
            }}>
              <strong style={{ fontSize: 13 }}>ARIA needs more information:</strong>
              <p style={{ margin: "4px 0 0", fontSize: 13 }}>{goalResult.clarificationMessage}</p>
            </div>
          )}

          {insightResult?.businessStory && (
            <div>
              <p style={{ fontSize: 12, fontWeight: 600, color: "var(--aria-text-subtle)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>
                Insight
              </p>
              <p style={{ margin: 0, fontSize: 14, lineHeight: 1.6 }}>{insightResult.businessStory}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default GoalAgent;
