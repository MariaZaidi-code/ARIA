import { useState, useRef, useEffect } from "react";
import { Send, Plus, MoreHorizontal, Sparkles } from "lucide-react";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  chartData?: { month: string; value: number }[];
};

interface Conversation {
  id: string;
  title: string;
  subtitle: string;
  date: string;
  messages: Message[];
}

const defaultConversations: Conversation[] = [
  {
    id: "c1",
    title: "Electronics revenue analysis",
    subtitle: "Sales Database · 4 messages",
    date: "Today",
    messages: [
      { id: "m1", role: "user", content: "Show me revenue for Electronics last quarter.", timestamp: "10:02 AM" },
      { id: "m2", role: "assistant", content: "Electronics generated $3.72M in Q3 2025, representing a 23.4% increase year-over-year. It was the top-performing category by both absolute revenue and growth rate.", timestamp: "10:02 AM", chartData: [
        { month: "Jul", value: 290000 }, { month: "Aug", value: 310000 }, { month: "Sep", value: 380000 },
      ]},
      { id: "m3", role: "user", content: "Why did it decrease in August?", timestamp: "10:03 AM" },
      { id: "m4", role: "assistant", content: "The August dip in Electronics revenue (from $310K to... wait, it actually increased from $290K in July to $310K in August). Looking at the data more carefully: Electronics grew consistently throughout Q3. The slight moderation in August growth rate (vs July) was likely due to a normal post-Prime Day cooldown — a well-documented seasonal pattern in consumer electronics.", timestamp: "10:03 AM" },
    ],
  },
  { id: "c2", title: "Q3 performance review", subtitle: "Sales Database · 6 messages", date: "Yesterday", messages: [] },
  { id: "c3", title: "Customer segmentation", subtitle: "CRM Database · 3 messages", date: "Dec 28", messages: [] },
  { id: "c4", title: "Pricing strategy analysis", subtitle: "Sales Database · 5 messages", date: "Dec 24", messages: [] },
];

const suggestions = [
  "What are the top revenue drivers this quarter?",
  "Show me year-over-year growth by category",
  "Which customers have churned recently?",
  "Summarize last week's performance",
];

export default function Copilot() {
  const [conversations, setConversations] = useState(defaultConversations);
  const [activeId, setActiveId] = useState("c1");
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const active = conversations.find((c) => c.id === activeId) || conversations[0];

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active.messages.length, isTyping]);

  const send = async (text?: string) => {
    const content = text || input;
    if (!content.trim()) return;
    setInput("");

    const userMsg: Message = {
      id: Date.now().toString(),
      role: "user",
      content,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    setConversations((prev) =>
      prev.map((c) => c.id === activeId ? { ...c, messages: [...c.messages, userMsg] } : c)
    );
    setIsTyping(true);

    try {
      const token = localStorage.getItem("aria_auth_token");
      const res = await fetch("/api/copilot", {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ question: content }),
      });
      const data = await res.json();
      const reply: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: data.answer || data.detail || "I couldn't generate a response.",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setConversations((prev) =>
        prev.map((c) => c.id === activeId ? { ...c, messages: [...c.messages, reply] } : c)
      );
    } catch {
      const reply: Message = {
        id: (Date.now() + 1).toString(),
        role: "assistant",
        content: "Sorry, I encountered an error. Please try again.",
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setConversations((prev) =>
        prev.map((c) => c.id === activeId ? { ...c, messages: [...c.messages, reply] } : c)
      );
    } finally {
      setIsTyping(false);
    }
  };

  const newChat = () => {
    const id = `c${Date.now()}`;
    setConversations((prev) => [{ id, title: "New conversation", subtitle: "Just now", date: "Today", messages: [] }, ...prev]);
    setActiveId(id);
  };

  return (
    <div className="flex h-full">
      {/* Conversation list */}
      <div className="w-64 border-r border-border bg-card/80 backdrop-blur-sm flex flex-col flex-shrink-0">
        <div className="px-3 py-3 border-b border-border">
          <div className="flex items-center justify-between mb-2">
            <p className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Conversations</p>
            <button onClick={newChat} className="premium-btn p-1 rounded-md hover:bg-secondary text-muted-foreground hover:text-foreground transition-all duration-150">
              <Plus size={13} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto custom-scroll">
          {conversations.map((conv) => (
            <button key={conv.id} onClick={() => setActiveId(conv.id)}
              className={`w-full text-left px-3 py-3 border-b border-border/50 transition-all duration-150 ${conv.id === activeId ? "bg-primary/8 border-l-2 border-l-primary" : "hover:bg-secondary/50 border-l-2 border-l-transparent"}`}>
              <p className="text-sm font-medium text-foreground truncate">{conv.title}</p>
              <p className="text-[11px] text-muted-foreground truncate mt-0.5">{conv.subtitle}</p>
              <p className="text-[10px] text-muted-foreground/60 mt-0.5">{conv.date}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        <div className="px-5 py-3 border-b border-border flex items-center justify-between flex-shrink-0">
          <div>
            <p className="text-sm font-semibold text-foreground">{active.title}</p>
            <p className="text-[11px] text-muted-foreground">{active.subtitle}</p>
          </div>
          <button className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-colors">
            <MoreHorizontal size={14} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4 custom-scroll">
          {active.messages.length === 0 && !isTyping && (
            <div className="flex flex-col items-center justify-center h-full text-center animate-fade-in">
              <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center mb-3 animate-float">
                <Sparkles size={18} className="text-primary" />
              </div>
              <p className="text-sm font-medium text-foreground">ARIA Copilot</p>
              <p className="text-xs text-muted-foreground mt-1">Ask me anything about your data</p>
            </div>
          )}

          {active.messages.map((msg) =>
            msg.role === "assistant" ? (
              <div key={msg.id} className="flex items-start gap-2.5 max-w-2xl animate-slide-in-left">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center mt-0.5">
                  <Sparkles size={11} className="text-primary" />
                </div>
                <div className="flex-1 space-y-1.5">
                  <div className="bg-card/90 border border-border/80 rounded-2xl rounded-tl-md px-4 py-3 shadow-sm backdrop-blur-sm">
                    <p className="text-[13px] text-foreground leading-relaxed">{msg.content}</p>
                    {msg.chartData && (
                      <div className="mt-2 pt-2 border-t border-border">
                        <p className="text-[10px] text-muted-foreground mb-1">Electronics Revenue · Jul-Dec 2025</p>
                        <div className="flex items-end gap-1 h-8">
                          {msg.chartData.map((d, i) => (
                            <div key={i} className="flex-1 bg-primary/20 rounded-t" style={{ height: `${(d.value / 400000) * 100}%` }} />
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                  <p className="text-[10px] text-muted-foreground px-1">{msg.timestamp}</p>
                </div>
              </div>
            ) : (
              <div key={msg.id} className="flex items-start gap-2.5 max-w-2xl ml-auto flex-row-reverse animate-slide-in-right">
                <div className="flex-shrink-0 w-6 h-6 rounded-full bg-primary/20 flex items-center justify-center text-[10px] font-semibold text-primary mt-0.5">A</div>
                <div className="space-y-1">
                  <div
                    className="rounded-2xl rounded-tr-md px-4 py-3 shadow-md text-white"
                    style={{ background: "var(--gradient-primary)" }}
                  >
                    <p className="text-[13px] leading-relaxed">{msg.content}</p>
                  </div>
                  <p className="text-[10px] text-muted-foreground px-1 text-right">{msg.timestamp}</p>
                </div>
              </div>
            )
          )}

          {isTyping && (
            <div className="flex items-start gap-2.5 max-w-2xl animate-slide-in-left">
              <div className="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center">
                <Sparkles size={11} className="text-primary" />
              </div>
              <div className="bg-card/90 border border-border/80 rounded-2xl rounded-tl-md px-4 py-3 shadow-sm backdrop-blur-sm flex items-center gap-1.5">
                <span className="typing-dot" />
                <span className="typing-dot" />
                <span className="typing-dot" />
              </div>
            </div>
          )}
          <div ref={endRef} />
        </div>

        {/* Suggestion chips */}
        <div className="px-5 pb-2 flex flex-wrap gap-1.5">
          {suggestions.map((s) => (
            <button key={s} onClick={() => send(s)}
              className="text-[11px] px-2.5 py-1 bg-secondary border border-border rounded-full text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors">
              {s}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="px-5 pb-4 flex-shrink-0">
          <div className="flex items-end gap-2 bg-card border border-border rounded-xl px-3.5 py-2.5 focus-within:border-primary/50 transition-colors">
            <input value={input} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask ARIA anything about your data..."
              className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none" />
            <button onClick={() => send()}
              className={`p-1.5 rounded-lg transition-all ${input.trim() ? "bg-primary text-primary-foreground hover:opacity-90" : "bg-secondary text-muted-foreground"}`}>
              <Send size={13} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
