import { useState } from "react";
import { Bot, Cpu, Shield, Zap, CheckCircle2 } from "lucide-react";

const LLM_OPTIONS = [
  {
    id: "cloud",
    label: "Cloud AI",
    sublabel: "Groq-powered",
    icon: Zap,
    badge: "Fast",
    description: "Lightning-fast cloud processing with GPT-4 class models.",
    speed: "Instant",
    privacy: "Cloud-processed",
  },
  {
    id: "local",
    label: "Local AI",
    sublabel: "On-device",
    icon: Shield,
    badge: "Private",
    description: "Keep all data on your machine. Full privacy guaranteed.",
    speed: "Hardware-dependent",
    privacy: "100% local",
  },
];

function LLMSelection({ onSelectLLM }) {
  const [selected, setSelected] = useState(null);

  const handleContinue = () => {
    if (selected) onSelectLLM(selected);
  };

  return (
    <div className="llm-page">
      <div className="llm-container">
        <div className="llm-logo">
          <div className="llm-logo-icon">A</div>
        </div>

        <div className="llm-header">
          <h1>Choose your AI engine</h1>
          <p>Select how ARIA processes your analytics. You can change this later.</p>
        </div>

        <div className="llm-options">
          {LLM_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={`llm-card ${selected === opt.id ? "selected" : ""}`}
              onClick={() => setSelected(opt.id)}
            >
              <div className="llm-card-top">
                <div className="llm-card-icon-wrap">
                  <opt.icon size={20} />
                </div>
                <span className={`llm-badge ${opt.badge.toLowerCase()}`}>
                  {opt.badge}
                </span>
              </div>

              <div className="llm-card-body">
                <h3>{opt.label}</h3>
                <span className="llm-sublabel">{opt.sublabel}</span>
                <p>{opt.description}</p>
              </div>

              <div className="llm-card-meta">
                <div>
                  <span className="llm-meta-label">Speed</span>
                  <span className="llm-meta-value">{opt.speed}</span>
                </div>
                <div>
                  <span className="llm-meta-label">Privacy</span>
                  <span className="llm-meta-value">{opt.privacy}</span>
                </div>
              </div>

              <div className="llm-card-radio">
                <div className={`llm-radio ${selected === opt.id ? "checked" : ""}`}>
                  {selected === opt.id && <CheckCircle2 size={14} />}
                </div>
              </div>
            </button>
          ))}
        </div>

        <button
          className="llm-continue-btn"
          disabled={!selected}
          onClick={handleContinue}
        >
          Continue
        </button>
      </div>
    </div>
  );
}

export default LLMSelection;
