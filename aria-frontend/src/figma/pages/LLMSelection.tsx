import { useState } from "react";
import { Zap, Shield, CheckCircle2 } from "lucide-react";

interface LLMSelectionProps {
  onSelectLLM: (mode: string) => void;
}

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

export default function LLMSelection({ onSelectLLM }: LLMSelectionProps) {
  const [selected, setSelected] = useState<string | null>(null);

  return (
    <div className="min-h-screen flex items-center justify-center p-6" style={{ background: "var(--background)" }}>
      <div className="w-full max-w-lg animate-fade-in-scale">
        {/* Logo */}
        <div className="flex items-center justify-center gap-2 mb-8">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-sm"
            style={{ background: "var(--gradient-primary)" }}
          >
            A
          </div>
          <span className="text-xl font-semibold" style={{ color: "var(--foreground)" }}>
            ARIA
          </span>
        </div>

        <h1
          className="text-center text-2xl font-bold mb-1"
          style={{ color: "var(--foreground)" }}
        >
          Choose your AI engine
        </h1>
        <p className="text-center text-sm mb-8" style={{ color: "var(--muted-foreground)" }}>
          Select how ARIA processes your analytics. You can change this later.
        </p>

        <div className="space-y-3 mb-6">
          {LLM_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              onClick={() => setSelected(opt.id)}
              className="w-full text-left rounded-xl p-5 transition-all animate-fade-in"
              style={{
                background: "var(--card)",
                border: selected === opt.id
                  ? "2px solid var(--primary)"
                  : "1px solid var(--border)",
                boxShadow: selected === opt.id ? "var(--shadow-glow)" : "var(--shadow-sm)",
              }}
            >
              <div className="flex items-start justify-between mb-3">
                <div className="flex items-center gap-3">
                  <div
                    className="w-10 h-10 rounded-lg flex items-center justify-center"
                    style={{
                      background: selected === opt.id ? "var(--primary-light)" : "var(--muted)",
                      color: selected === opt.id ? "var(--primary)" : "var(--muted-foreground)",
                    }}
                  >
                    <opt.icon size={20} />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold" style={{ color: "var(--foreground)" }}>
                        {opt.label}
                      </span>
                      <span
                        className="badge-gradient text-xs px-2 py-0.5 rounded-full font-medium"
                      >
                        {opt.badge}
                      </span>
                    </div>
                    <span className="text-xs" style={{ color: "var(--muted-foreground)" }}>
                      {opt.sublabel}
                    </span>
                  </div>
                </div>
                <div
                  className="w-5 h-5 rounded-full flex items-center justify-center mt-1"
                  style={{
                    border: selected === opt.id
                      ? "2px solid var(--primary)"
                      : "2px solid var(--border)",
                    background: selected === opt.id ? "var(--primary)" : "transparent",
                  }}
                >
                  {selected === opt.id && <CheckCircle2 size={12} color="white" />}
                </div>
              </div>

              <p className="text-sm mb-3" style={{ color: "var(--muted-foreground)" }}>
                {opt.description}
              </p>

              <div className="flex gap-6 text-xs">
                <div>
                  <span className="font-medium" style={{ color: "var(--foreground)" }}>Speed: </span>
                  <span style={{ color: "var(--muted-foreground)" }}>{opt.speed}</span>
                </div>
                <div>
                  <span className="font-medium" style={{ color: "var(--foreground)" }}>Privacy: </span>
                  <span style={{ color: "var(--muted-foreground)" }}>{opt.privacy}</span>
                </div>
              </div>
            </button>
          ))}
        </div>

        <button
          disabled={!selected}
          onClick={() => selected && onSelectLLM(selected)}
          className="premium-btn btn-glow w-full py-2.5 rounded-lg text-sm font-semibold text-white transition-all disabled:opacity-40"
          style={{ background: "var(--gradient-primary)" }}
        >
          Continue
        </button>
      </div>
    </div>
  );
}
