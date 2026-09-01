import { useEffect, useRef, useState } from "react";

const PROCESSING_STEPS = [
  "Understanding your question",
  "Identifying relevant data",
  "Running analysis",
  "Preparing insights",
];

const CONTEXT_SUGGESTIONS = {
  dashboard: [
    "What is driving my latest results?",
    "Explain the anomalies in my data",
    "What should my business do next?",
  ],
  askAria: [
    "Show me the top trends in my data",
    "What changed recently in my data?",
    "Find anomalies in my key metrics",
  ],
  dataSource: ["What data do I have connected?", "Summarize what my data contains"],
  schema: [
    "Explain the relationships in my tables",
    "Which tables are most important for analysis?",
  ],
  history: ["What patterns repeat across my past analyses?"],
  savedReports: ["Which saved reports should I review first?"],
  help: ["How do I get the most out of ARIA?"],
};

function Copilot({
  open,
  setOpen,
  onAsk,
  processing,
  connectionReady,
  schemaReady,
  suggestions,
  activePage,
  onNavigate,
  hasResult,
}) {
  const [messages, setMessages] = useState([]);

  const [draft, setDraft] = useState("");

  const [sending, setSending] = useState(false);

  const [activeStep, setActiveStep] = useState(0);

  const messagesEndRef = useRef(null);

  const inputRef = useRef(null);

  const stepTimersRef = useRef([]);

  const nextIdRef = useRef(1);

  const nextMessageId = () => `msg-${nextIdRef.current++}`;

  // Scroll to the newest message.
  useEffect(() => {
    if (open) {
      messagesEndRef.current?.scrollIntoView({ block: "end" });
    }
  }, [messages, sending, open]);

  // Focus the composer when the drawer opens.
  useEffect(() => {
    if (open) {
      const focusTimer = setTimeout(() => inputRef.current?.focus(), 320);

      return () => clearTimeout(focusTimer);
    }

    return undefined;
  }, [open]);

  // Rule: only one pipeline can run at a time.
  useEffect(() => {
    if (!processing) {
      const resetSending = setTimeout(() => setSending(false), 0);

      return () => clearTimeout(resetSending);
    }

    return undefined;
  }, [processing]);

  useEffect(() => {
    return () => {
      stepTimersRef.current.forEach((timer) => clearTimeout(timer));
    };
  }, []);

  const runStepAnimation = () => {
    setActiveStep(0);

    stepTimersRef.current.forEach((timer) => clearTimeout(timer));

    stepTimersRef.current = PROCESSING_STEPS.map((step, index) =>
      setTimeout(() => setActiveStep(index + 1), 850 * (index + 1)),
    );
  };

  const buildSuggestions = () => {
    const chips = [];

    const contextSlice = (CONTEXT_SUGGESTIONS[activePage] || CONTEXT_SUGGESTIONS.askAria).slice(
      0,
      2,
    );

    chips.push(...contextSlice.map((label) => ({ label, context: true })));

    if (connectionReady && Array.isArray(suggestions) && suggestions.length) {
      suggestions.slice(0, 3).forEach((label) => chips.push({ label, context: false }));
    }

    return chips.slice(0, 4);
  };

  const submitDraft = (rawText) => {
    const text = String(rawText || "").trim();

    if (!text || sending) {
      return;
    }

    const userMessage = {
      id: nextMessageId(),
      role: "user",
      text,
    };

    setMessages((current) => [...current, userMessage]);

    setDraft("");

    setSending(true);

    runStepAnimation();

    onAsk(text)
      .then((result) => {
        const ariaMessage = {
          id: nextMessageId(),
          role: "aria",
          result,
        };

        setMessages((current) => [...current, ariaMessage]);
      })
      .catch((error) => {
        const ariaMessage = {
          id: nextMessageId(),
          role: "error",
          text: error?.message || "ARIA could not complete this analysis.",
        };

        setMessages((current) => [...current, ariaMessage]);
      })
      .finally(() => {
        stepTimersRef.current.forEach((timer) => clearTimeout(timer));

        setSending(false);
      });
  };

  const buildAnalysisMessage = (message) => {
    const result = message.result || {};

    const goalData = result.goalData || {};

    const analyticsData = result.analyticsData || {};

    const insightData = result.insightData || {};

    const story =
      insightData.businessStory ||
      goalData.message ||
      goalData.interpretedGoal ||
      "ARIA finished the analysis.";

    const kpis = Array.isArray(analyticsData.kpis)
      ? analyticsData.kpis.slice(0, 3)
      : [];

    const findings = Array.isArray(insightData.keyInsights)
      ? insightData.keyInsights.slice(0, 3)
      : [];

    const rowCount = goalData.processedDataSummary?.rowCount;

    return (
      <div className="copilot-analysis">
        <div className="copilot-analysis-top">
          <span className="copilot-analysis-tag">✦ ARIA Analysis</span>

          <h4>{message.result?.submittedQuestion}</h4>
        </div>

        <div className="copilot-analysis-body">
          <p className="copilot-story">{story}</p>

          {kpis.length > 0 && (
            <div className="copilot-kpi-row">
              {kpis.map((kpi, index) => (
                <div className="copilot-kpi-mini" key={`${kpi.label}-${index}`}>
                  <span>{kpi.label}</span>

                  <strong>{kpi.value}</strong>
                </div>
              ))}

              {typeof rowCount === "number" && (
                <div className="copilot-kpi-mini">
                  <span>Rows</span>

                  <strong>{rowCount}</strong>
                </div>
              )}
            </div>
          )}

          {findings.length > 0 && (
            <ul className="copilot-analyses">
              {findings.map((finding, index) => (
                <li key={`${finding.title}-${index}`}>{finding.title}</li>
              ))}
            </ul>
          )}
        </div>

        <div className="copilot-analysis-actions">
          <button
            type="button"
            className="copilot-action-btn primary"
            onClick={() => onNavigate("dashboard")}
          >
            View dashboard
          </button>

          <button
            type="button"
            className="copilot-action-btn"
            onClick={() => submitDraft(message.result?.submittedQuestion)}
          >
            Re-run analysis
          </button>
        </div>
      </div>
    );
  };

  const buildSuggestionArea = () => {
    if (messages.length > 0 && !hasResult) {
      return (
        <>
          <div className="copilot-suggestions-label">Suggested</div>

          <div className="copilot-suggestions">
            {buildSuggestions().map((chip, index) => (
              <button
                type="button"
                key={`${chip.label}-${index}`}
                className="copilot-chip"
                disabled={sending}
                onClick={() => submitDraft(chip.label)}
              >
                <span className="copilot-chip-icon" aria-hidden="true">
                  ↗
                </span>

                {chip.label}
              </button>
            ))}
          </div>
        </>
      );
    }

    return null;
  };

  return (
    <>
      <button
        type="button"
        className={`copilot-launcher ${hasResult ? "has-result" : ""}`}
        onClick={() => setOpen(true)}
        aria-label="Open ARIA Copilot"
      >
        <span className="copilot-launcher-icon" aria-hidden="true">
          ✦
        </span>

        <span className="copilot-launcher-text">
          {hasResult ? "ARIA" : "Ask ARIA"}

          {hasResult && <small>Insight ready</small>}
        </span>

        <span className="copilot-launcher-dot" title="Online" />
      </button>

      {open && (
        <>
          <div className="copilot-backdrop" onClick={() => setOpen(false)} />

          <aside className="copilot-drawer" aria-label="ARIA Copilot">
            <div className="copilot-header">
              <div className="copilot-header-brand">
                <span className="copilot-brandmark">✦</span>

                <div>
                  <h3 className="copilot-header-title">ARIA</h3>

                  <div className="copilot-header-sub">
                    <span className="copilot-status-dot" />

                    <span>AI Analytics Copilot · Online</span>
                  </div>
                </div>
              </div>

              <button
                type="button"
                className="copilot-close"
                onClick={() => setOpen(false)}
                aria-label="Close ARIA Copilot"
              >
                ×
              </button>
            </div>

            <div className="copilot-body">
              {messages.length === 0 && (
                <div className="copilot-greeting">
                  <h3>Hi, I&apos;m ARIA.</h3>

                  <p>What would you like to understand about your data?</p>
                </div>
              )}

              {messages.map((message) => {
                if (message.role === "user") {
                  return (
                    <div className="copilot-msg copilot-msg-user" key={message.id}>
                      {message.text}
                    </div>
                  );
                }

                if (message.role === "aria") {
                  return buildAnalysisMessage(message);
                }

                return (
                  <div className="copilot-msg copilot-error" key={message.id}>
                    <strong>Something went wrong.</strong>

                    <p>{message.text}</p>

                    <p>Try rephrasing your question, or check that your data source is connected.</p>
                  </div>
                );
              })}

              {sending && (
                <div className="copilot-processing" aria-live="polite">
                  <div className="copilot-processing-title">
                    <span className="copilot-spinner-mini" />

                    <span>✦ ARIA is analyzing your data</span>
                  </div>

                  {PROCESSING_STEPS.map((step, index) => {
                    const stepNumber = index + 1;

                    let statusClass = "pending";

                    if (stepNumber < activeStep) {
                      statusClass = "done";
                    } else if (stepNumber === activeStep) {
                      statusClass = "active";
                    }

                    return (
                      <div className={`copilot-step ${statusClass}`} key={step}>
                        <span className="copilot-step-state" aria-hidden="true">
                          {statusClass === "done" ? "✓" : ""}
                        </span>

                        {step}
                      </div>
                    );
                  })}
                </div>
              )}

              {sending && (
                <div className="copilot-typing">
                  <div className="copilot-typing-bubble">
                    <span className="copilot-typing-dot" />

                    <span className="copilot-typing-dot" />

                    <span className="copilot-typing-dot" />
                  </div>
                </div>
              )}

              {!connectionReady && messages.length === 0 && (
                <div className="copilot-error">
                  <strong>No data source connected yet.</strong>

                  <div className="copilot-analysis-actions" style={{ padding: "12px 0 0" }}>
                    <button
                      type="button"
                      className="copilot-action-btn primary"
                      onClick={() => onNavigate("dataSource")}
                    >
                      Connect a data source
                    </button>
                  </div>
                </div>
              )}

              {connectionReady && !schemaReady && messages.length === 0 && (
                <div className="copilot-aria-confirm">
                  <span aria-hidden="true">⏳</span>

                  <span>Schema Agent is still analyzing the connected data. Ask again shortly.</span>
                </div>
              )}

              {buildSuggestionArea()}

              <div ref={messagesEndRef} />
            </div>

            <form
              className="copilot-composer"
              onSubmit={(event) => {
                event.preventDefault();

                submitDraft(draft);
              }}
            >
              <textarea
                ref={inputRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Ask ARIA anything..."
                rows={1}
                disabled={sending}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();

                    submitDraft(draft);
                  }
                }}
              />

              <button
                type="submit"
                className="copilot-send"
                disabled={sending || draft.trim() === ""}
                aria-label="Send question to ARIA"
              >
                <span aria-hidden="true">↑</span>
              </button>
            </form>
          </aside>
        </>
      )}
    </>
  );
}

export default Copilot;