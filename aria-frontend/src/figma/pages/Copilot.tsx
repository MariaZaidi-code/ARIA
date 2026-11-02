import { useState, useRef, useEffect, useMemo, useCallback } from "react";
import {
  Send, Plus, MoreHorizontal, Sparkles, Search, Trash2, PanelLeft, Copy, Check,
  RotateCcw, AlertTriangle, MessageSquare, User,
} from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, LineChart, Line, PieChart, Pie, Cell } from "recharts";
import { useTheme } from "../App";
import Evidence from "../components/Evidence";
import AIProcessingIndicator from "../components/AIProcessingIndicator";
import { BizTooltip } from "../components/charts";
import { DocumentAnswer } from "../components/documents/DocumentAnswer";
import { ConfirmDialog } from "../components/documents/ConfirmDialog";
import { colorForName } from "../lib/charts";
import { fmtBiz } from "../lib/format";
import { apiFetch, AI_ANSWER_TIMEOUT_MS } from "../../services/api";
import { KEYS, storage, sessionStore } from "../../utils/storage";
import { useReadOnly, READ_ONLY_HINT } from "../lib/readonly";
import "../components/documents/documents-ui.css";
import "./Copilot.css";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  sql?: string | null;
  provider?: string | null;
  providerFailed?: boolean;
  rows?: Record<string, any>[];
  chart?: { type: string; x: string; y: string; reason?: string } | null;
  /** The request failed (network/server); the bubble offers "Try again". */
  error?: boolean;
  /** Question this reply answered, so a failed reply can be retried. */
  question?: string;
};

/** Provider/LLM failure signals in a copilot payload or error text. */
function isProviderFailure(data: any, errText = ""): boolean {
  const hay = `${data?.error || ""} ${data?.detail || ""} ${data?.answer || ""} ${errText}`;
  return /provider|llm|model|groq|ollama|deepseek|omniroute|\b403\b|\b404\b|access denied|could not reach|timed out/i.test(hay);
}

interface Conversation {
  id: string;
  title: string;
  subtitle: string;
  date: string;
  messages: Message[];
  // Epoch ms; absent on chats saved before the redesign (grouped as "Earlier").
  createdAt?: number;
  updatedAt?: number;
}

const FALLBACK_SUGGESTIONS = [
  "What are the main metrics in this dataset?",
  "Show me a summary of the data",
  "Which categories have the most records?",
  "What trends do you see in the data?",
];

const NEW_TITLE = "New conversation";
const MAX_QUESTION = 4000; // matches CopilotRequest.question max_length
const DAY = 86_400_000;

const clock = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const titleFrom = (text: string) => {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > 48 ? `${flat.slice(0, 48).trimEnd()}…` : flat;
};

/** One-line preview without Markdown markers (bold, bullets, headings, table pipes). */
function plainPreview(text: string): string {
  return text
    .replace(/^\s{0,3}(?:#{1,6}|[-*•]|\d+[.)])\s+/gm, "")
    .replace(/\*\*|__|`/g, "")
    .replace(/\|/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function relativeTime(ts?: number): string {
  if (!ts) return "";
  const diff = Date.now() - ts;
  if (diff < 60_000) return "Just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} min ago`;
  const date = new Date(ts);
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (ts >= today.getTime()) return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (ts >= today.getTime() - DAY) return "Yesterday";
  return date.toLocaleDateString([], { month: "short", day: "numeric" });
}

function historyGroup(ts?: number): string {
  if (!ts) return "Earlier";
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const start = today.getTime();
  if (ts >= start) return "Today";
  if (ts >= start - DAY) return "Yesterday";
  if (ts >= start - 7 * DAY) return "Previous 7 days";
  return "Older";
}
const GROUP_ORDER = ["Today", "Yesterday", "Previous 7 days", "Older", "Earlier"];

// Render the chart-ready payload returned by the backend as a fully
// interactive chart (hover tooltips, axis formatting). The type is chosen
// dynamically from the question + returned data (bar/line/pie/scatter).
function renderChart(msg: Message, isDark?: boolean) {
  const rows = msg.rows || [];
  const spec = msg.chart;
  if (!spec || !rows.length) return null;
  const x = spec.x;
  const y = spec.y;
  // Guard shape drift: if the spec keys don't exist in the rows, render
  // nothing instead of a flat zero chart. Never invent zeros.
  if (!x || !y || !rows.some((r) => r[x] !== undefined && r[y] !== undefined && r[y] !== null)) return null;
  const data = rows
    .map((r) => ({ [x]: String(r[x] ?? ""), [y]: Number(r[y]) }))
    .filter((d) => d[x] !== "" && Number.isFinite(d[y]))
    .slice(0, 24);
  if (!data.length) return null;
  const grid = isDark ? "#2A2A35" : "#E5E7EB";
  const axis = isDark ? "#8889A0" : "#9CA3AF";
  const tick = { fontSize: 11, fill: axis };
  const isPie = spec.type === "pie" || spec.type === "doughnut";
  const isLine = spec.type === "line" || spec.type === "area";
  const horizontal = spec.type === "bar_horizontal" || (!isLine && !isPie && data.length > 8);
  return (
    <div className="mt-2 pt-2 border-t border-border">
      {isPie ? (
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Tooltip content={<BizTooltip metricNames={{ value: y }} />} />
            <Pie data={data} dataKey={y} nameKey={x} outerRadius={70} paddingAngle={2}>
              {data.map((d, i) => (
                <Cell key={i} fill={colorForName(String(d[x]))} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
      ) : isLine ? (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
            <XAxis dataKey={x} tick={tick} axisLine={false} tickLine={false} minTickGap={24} />
            <YAxis tick={tick} axisLine={false} tickLine={false} width={52} tickFormatter={(v: number) => fmtBiz(v)} />
            <Tooltip content={<BizTooltip metricNames={{ [y]: y }} />} />
            <Line type="monotone" dataKey={y} stroke={colorForName(String(y))} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} name={y} />
          </LineChart>
        </ResponsiveContainer>
      ) : horizontal ? (
        <ResponsiveContainer width="100%" height={Math.max(160, data.length * 32)}>
          <BarChart data={data} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke={grid} horizontal={false} />
            <XAxis type="number" tick={tick} axisLine={false} tickLine={false} tickFormatter={(v: number) => fmtBiz(v)} />
            <YAxis type="category" dataKey={x} tick={tick} axisLine={false} tickLine={false} width={110} />
            <Tooltip content={<BizTooltip metricNames={{ [y]: y }} />} cursor={{ fill: "var(--secondary)" }} />
            <Bar dataKey={y} radius={[0, 5, 5, 0]} name={y}>
              {data.map((d, i) => (
                <Cell key={i} fill={colorForName(String(d[x]))} fillOpacity={i === 0 ? 1 : 0.7} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke={grid} vertical={false} />
            <XAxis dataKey={x} tick={tick} axisLine={false} tickLine={false} interval={data.length > 12 ? Math.floor(data.length / 12) : 0} />
            <YAxis tick={tick} axisLine={false} tickLine={false} width={52} tickFormatter={(v: number) => fmtBiz(v)} />
            <Tooltip content={<BizTooltip metricNames={{ [y]: y }} />} cursor={{ fill: "var(--secondary)" }} />
            <Bar dataKey={y} radius={[5, 5, 0, 0]} name={y}>
              {data.map((d, i) => (
                <Cell key={i} fill={colorForName(String(d[x]))} fillOpacity={i === 0 ? 1 : 0.7} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
      <p className="text-[10px] text-muted-foreground mt-1.5">{spec.reason || spec.type}</p>
    </div>
  );
}

/** Copy-to-clipboard with a short "Copied" confirmation. */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      className="cpl-copy"
      aria-label={copied ? "Answer copied" : "Copy answer"}
      onClick={async () => {
        try { await navigator.clipboard.writeText(text); setCopied(true); } catch { /* clipboard blocked */ }
      }}
    >
      {copied ? <Check size={11} /> : <Copy size={11} />} {copied ? "Copied" : "Copy"}
    </button>
  );
}

export default function Copilot({ initialQuestion = "", analysisResult = null, goalResult = null }: { initialQuestion?: string; analysisResult?: any; goalResult?: any }) {
  void analysisResult; void goalResult;
  const { isDark } = useTheme();
  const readOnly = useReadOnly();
  // Data-driven starter questions (4, from the connected schema).
  // Refreshed on mount and whenever a new chat starts (source may change).
  const [suggestions, setSuggestions] = useState<string[]>(FALLBACK_SUGGESTIONS);
  const refreshSuggestions = async () => {
    try {
      const data: any = await apiFetch("/copilot/suggestions");
      if (Array.isArray(data.suggestions) && data.suggestions.length) {
        setSuggestions(data.suggestions.slice(0, 4));
      }
    } catch { /* fallback list stays */ }
  };
  useEffect(() => { refreshSuggestions(); }, []);
  // Per-user persistence (§13): conversations survive refresh. Rows are
  // trimmed on save so one chat cannot exhaust localStorage quota.
  // The key + initial chats resolve once (useMemo/useState initializer —
  // never parsed inline during render).
  const chatsKey = useMemo(() => {
    const u: any = storage.get(KEYS.authUser, null);
    return storage.scoped(KEYS.copilotChats, u);
  }, []);
  const loadChats = (): Conversation[] => {
    const parsed = storage.get(chatsKey, []);
    return Array.isArray(parsed) ? (parsed as Conversation[]).slice(0, 10) : [];
  };
  const [conversations, setConversations] = useState<Conversation[]>(loadChats);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  // Conversation awaiting an answer (one request at a time).
  const [pendingId, setPendingId] = useState<string | null>(null);
  // Lifecycle-driven AI stage (real request milestones, never timers):
  // 0 = request sent · 1 = response headers arrived · 2 = payload parsed,
  // rendering the answer. Unmounted when the request settles.
  const [copilotStage, setCopilotStage] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [toDelete, setToDelete] = useState<Conversation | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const consumedPrefill = useRef("");

  const active = conversations.find((c) => c.id === activeId) || conversations[0] || null;
  const isTyping = pendingId !== null && pendingId === active?.id;

  // Persist on every change (trimmed: 10 chats, 30 messages each, 24 rows).
  // Versioned key + quota-guarded write; overflow stays session-only.
  useEffect(() => {
    const trimmed = conversations.slice(0, 10).map((c) => ({
      ...c,
      messages: c.messages.slice(-30).map((m) => ({
        ...m,
        rows: Array.isArray(m.rows) ? m.rows.slice(0, 24) : m.rows,
      })),
    }));
    storage.set(chatsKey, trimmed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversations]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [active?.id, active?.messages.length, isTyping]);

  // Grow the composer with its content (capped by CSS max-height).
  useEffect(() => {
    const box = inputRef.current;
    if (!box) return;
    box.style.height = "auto";
    box.style.height = `${Math.min(box.scrollHeight, 168)}px`;
  }, [input]);

  // Options menu: close on outside click or Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onDown = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setMenuOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  // History drawer (tablet/phone): Escape closes it.
  useEffect(() => {
    if (!historyOpen) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setHistoryOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [historyOpen]);

  /** Apply a change to one conversation and move it to the top (most recent). */
  const touch = useCallback((id: string, change: (c: Conversation) => Conversation) => {
    setConversations((prev) => {
      const target = prev.find((c) => c.id === id);
      if (!target) return prev; // deleted while the answer was pending
      const updated = { ...change(target), updatedAt: Date.now() };
      return [updated, ...prev.filter((c) => c.id !== id)];
    });
  }, []);

  /** Ask the backend and append the assistant reply to ``targetId``. */
  const request = async (targetId: string, content: string) => {
    setPendingId(targetId);
    setCopilotStage(0);
    let reply: Message;
    try {
      // Chart context stashed by Decision Center / other pages (§38): measured
      // evidence travels with the question so Copilot answers about THIS chart.
      let chartCtx: any = null;
      try {
        const raw = sessionStore.getItem("aria_copilot_context");
        if (raw) { chartCtx = JSON.parse(raw); sessionStore.removeItem("aria_copilot_context"); }
      } catch { chartCtx = null; }
      const data: any = await apiFetch("/copilot", {
        method: "POST",
        body: JSON.stringify(chartCtx ? { question: content, context: chartCtx } : { question: content }),
        // Cold local models can take minutes on first load — don't cut them off.
        timeoutMs: AI_ANSWER_TIMEOUT_MS,
      });
      // Response headers arrived — analysis running server-side.
      setCopilotStage(1);
      // Payload parsed — building the answer rendering.
      setCopilotStage(2);
      reply = {
        id: `${Date.now()}-a`,
        role: "assistant",
        content: data.answer || data.detail || "I couldn't generate a response.",
        timestamp: clock(),
        sql: data.sql || null,
        provider: data.provider || null,
        providerFailed: !data.ok && isProviderFailure(data),
        rows: Array.isArray(data.data) ? data.data : [],
        chart: data.chart || null,
        question: content,
      };
    } catch {
      reply = {
        id: `${Date.now()}-a`,
        role: "assistant",
        content: "I couldn't get an answer just now. Check your connection or AI engine, then try again.",
        timestamp: clock(),
        error: true,
        question: content,
      };
    }
    touch(targetId, (c) => ({ ...c, messages: [...c.messages, reply] }));
    setPendingId(null);
  };

  const send = async (text?: string) => {
    const content = (text ?? input).trim();
    if (readOnly || !content || pendingId || content.length > MAX_QUESTION) return;
    setInput("");

    let targetId = active?.id || null;
    if (!targetId) {
      const now = Date.now();
      const id = `c${now}`;
      setConversations((prev) => [{
        id, title: titleFrom(content), subtitle: "", date: "", messages: [], createdAt: now, updatedAt: now,
      }, ...prev]);
      targetId = id;
    }
    setActiveId(targetId);

    const userMsg: Message = { id: `${Date.now()}-u`, role: "user", content, timestamp: clock() };
    touch(targetId, (c) => ({
      ...c,
      title: !c.messages.length && (c.title === NEW_TITLE || !c.title) ? titleFrom(content) : c.title,
      messages: [...c.messages, userMsg],
    }));
    await request(targetId, content);
  };

  /** Drop a failed reply and ask the same question again. */
  const retry = async (conversationId: string, msg: Message) => {
    if (!msg.question || pendingId || readOnly) return;
    touch(conversationId, (c) => ({ ...c, messages: c.messages.filter((m) => m.id !== msg.id) }));
    await request(conversationId, msg.question);
  };

  const switchToLocalAndRetry = async (conversationId: string, msg: Message) => {
    try {
      await apiFetch("/provider/switch", {
        method: "POST",
        body: JSON.stringify({ provider: "local" }),
      });
    } catch { /* best-effort; the retry reports its own outcome */ }
    await retry(conversationId, msg);
  };

  // Handoff from other pages ("Ask ARIA" buttons): send once per distinct
  // question, so the conversation continues here.
  useEffect(() => {
    const q = (initialQuestion || "").trim();
    if (q && consumedPrefill.current !== q) {
      consumedPrefill.current = q;
      send(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  const newChat = () => {
    setMenuOpen(false);
    setHistoryOpen(false);
    // Reuse an untouched empty chat instead of stacking blank ones.
    const blank = conversations.find((c) => !c.messages.length);
    if (blank) {
      setActiveId(blank.id);
    } else {
      const now = Date.now();
      const id = `c${now}`;
      setConversations((prev) => [{ id, title: NEW_TITLE, subtitle: "", date: "", messages: [], createdAt: now, updatedAt: now }, ...prev]);
      setActiveId(id);
    }
    refreshSuggestions();
    window.setTimeout(() => inputRef.current?.focus(), 0);
  };

  const deleteConversation = (id: string) => {
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (active?.id === id) setActiveId(null);
    setToDelete(null);
    setMenuOpen(false);
  };

  const openConversation = (id: string) => {
    setActiveId(id);
    setHistoryOpen(false);
  };

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const matches = conversations.filter((c) => !needle
      || c.title.toLowerCase().includes(needle)
      || c.messages.some((m) => m.content.toLowerCase().includes(needle)));
    const byGroup = new Map<string, Conversation[]>();
    for (const conv of matches) {
      const key = historyGroup(conv.updatedAt);
      byGroup.set(key, [...(byGroup.get(key) || []), conv]);
    }
    return GROUP_ORDER.filter((g) => byGroup.has(g)).map((g) => ({ label: g, items: byGroup.get(g)! }));
  }, [conversations, query]);

  const lastProvider = active
    ? [...active.messages].reverse().find((m) => m.role === "assistant" && m.provider)?.provider
    : null;
  const tooLong = input.length > MAX_QUESTION;
  const canSend = !readOnly && !pendingId && !!input.trim() && !tooLong;
  const showWelcome = !active || (!active.messages.length && !isTyping);

  return (
    <div className={`cpl-page${historyOpen ? " history-open" : ""}`}>
      <div className="cpl-backdrop" onClick={() => setHistoryOpen(false)} aria-hidden="true" />

      {/* Conversation history */}
      <aside className="cpl-sidebar" aria-label="Conversation history">
        <div className="cpl-sidebar-head">
          <div className="cpl-sidebar-title">
            <h2>Conversations</h2>
          </div>
          <button type="button" className="cpl-new-chat" onClick={newChat}>
            <Plus size={15} /> New chat
          </button>
          {conversations.length > 0 && (
            <label className="cpl-search">
              <Search size={13} />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search conversations"
                aria-label="Search conversations"
              />
            </label>
          )}
        </div>
        <nav className="cpl-history custom-scroll" aria-label="Saved conversations">
          {conversations.length === 0 ? (
            <div className="cpl-history-empty">
              <strong>No conversations yet</strong>
              Your chats with ARIA will appear here.
            </div>
          ) : groups.length === 0 ? (
            <div className="cpl-history-empty">
              <strong>No matches</strong>
              No conversation mentions “{query.trim()}”.
            </div>
          ) : groups.map((group) => (
            <section className="cpl-history-group" key={group.label}>
              <h3>{group.label}</h3>
              {group.items.map((conv) => {
                const last = conv.messages[conv.messages.length - 1];
                const preview = last
                  ? `${last.role === "user" ? "You: " : ""}${plainPreview(last.content)}`
                  : "No messages yet";
                const when = relativeTime(conv.updatedAt) || conv.date;
                return (
                  <div key={conv.id} className={`cpl-history-item${conv.id === active?.id ? " active" : ""}`}>
                    <button
                      type="button"
                      className="cpl-history-open"
                      onClick={() => openConversation(conv.id)}
                      aria-current={conv.id === active?.id ? "true" : undefined}
                    >
                      <strong>{conv.title || NEW_TITLE}</strong>
                      <span>{preview}</span>
                      <small>
                        {[when, conv.messages.length ? `${conv.messages.length} message${conv.messages.length === 1 ? "" : "s"}` : ""]
                          .filter(Boolean).join(" · ")}
                      </small>
                    </button>
                    <button
                      type="button"
                      className="cpl-history-delete"
                      aria-label={`Delete conversation ${conv.title || NEW_TITLE}`}
                      onClick={() => setToDelete(conv)}
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                );
              })}
            </section>
          ))}
        </nav>
      </aside>

      {/* Chat */}
      <section className="cpl-main" aria-label="Copilot chat">
        <header className="cpl-header">
          <button
            type="button"
            className="cpl-icon-button cpl-history-toggle"
            aria-label="Show conversation history"
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen(true)}
          >
            <PanelLeft size={16} />
          </button>
          <div className="cpl-header-text">
            <h2>{active && active.messages.length ? active.title : "ARIA Copilot"}</h2>
            <p>
              {active && active.messages.length
                ? [relativeTime(active.updatedAt) || active.subtitle, lastProvider ? `${lastProvider} mode` : ""].filter(Boolean).join(" · ")
                : "Ask questions about your connected data"}
            </p>
          </div>
          {active && (
            <div className="cpl-menu-wrap" ref={menuRef}>
              <button
                type="button"
                className="cpl-icon-button"
                onClick={() => setMenuOpen((o) => !o)}
                aria-label="Conversation options"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
              >
                <MoreHorizontal size={16} />
              </button>
              {menuOpen && (
                <div className="cpl-menu" role="menu">
                  <button type="button" role="menuitem" onClick={newChat}>
                    <Plus size={14} /> New chat
                  </button>
                  <button type="button" role="menuitem" className="danger" onClick={() => { setMenuOpen(false); setToDelete(active); }}>
                    <Trash2 size={14} /> Delete conversation
                  </button>
                </div>
              )}
            </div>
          )}
        </header>

        <div className="cpl-messages custom-scroll">
          {showWelcome ? (
            <div className="cpl-welcome">
              <span className="cpl-welcome-icon"><Sparkles size={24} /></span>
              <h2>ARIA Copilot</h2>
              <p>Ask anything about your connected data. I can summarise it, compare groups, spot trends and show the evidence behind each answer.</p>
              <div className="cpl-suggestions">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className="cpl-suggestion"
                    onClick={() => send(s)}
                    disabled={readOnly || !!pendingId}
                    title={readOnly ? READ_ONLY_HINT : undefined}
                  >
                    <MessageSquare size={14} /> {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="cpl-thread" role="log" aria-live="polite" aria-label="Conversation">
              {active!.messages.map((msg) =>
                msg.role === "assistant" ? (
                  <div key={msg.id} className="cpl-row assistant">
                    <span className="cpl-avatar assistant" aria-hidden="true"><Sparkles size={14} /></span>
                    <div className="cpl-bubble-wrap">
                      <div className={`cpl-bubble assistant${msg.error ? " error" : ""}`}>
                        {msg.error && (
                          <div className="cpl-error-title"><AlertTriangle size={13} /> Something went wrong</div>
                        )}
                        <DocumentAnswer text={msg.content} />
                        {(msg.error || msg.providerFailed) && msg.question && (
                          <div className="cpl-bubble-actions">
                            {msg.providerFailed ? (
                              <button
                                type="button"
                                className="cpl-action"
                                disabled={!!pendingId || readOnly}
                                onClick={() => switchToLocalAndRetry(active!.id, msg)}
                              >
                                <RotateCcw size={12} /> Switch to on-device AI and retry your question
                              </button>
                            ) : (
                              <button
                                type="button"
                                className="cpl-action"
                                disabled={!!pendingId || readOnly}
                                onClick={() => retry(active!.id, msg)}
                              >
                                <RotateCcw size={12} /> Try again
                              </button>
                            )}
                          </div>
                        )}
                        {renderChart(msg, isDark)}
                        {msg.sql && (
                          <div className="mt-2">
                            <Evidence
                              label="Evidence"
                              sections={[
                                { title: "Data analyzed", body: `Connected data${Array.isArray(msg.rows) ? ` — ${msg.rows.length} row${msg.rows.length === 1 ? "" : "s"} returned` : ""}.` },
                                { title: "How ARIA answered", body: "Ran a read-only query against the connected source and summarized the result in plain language." },
                              ]}
                              technical={(
                                <pre className="text-[10px] font-mono overflow-x-auto whitespace-pre-wrap">{msg.sql}</pre>
                              )}
                            />
                          </div>
                        )}
                      </div>
                      <div className="cpl-meta">
                        <span>{msg.timestamp}</span>
                        {!msg.error && <CopyButton text={msg.content} />}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div key={msg.id} className="cpl-row user">
                    <span className="cpl-avatar user" aria-hidden="true"><User size={14} /></span>
                    <div className="cpl-bubble-wrap">
                      <div className="cpl-bubble user">{msg.content}</div>
                      <div className="cpl-meta"><span>{msg.timestamp}</span></div>
                    </div>
                  </div>
                ),
              )}

              {isTyping && (
                <div className="cpl-row assistant" aria-label="ARIA is thinking">
                  <span className="cpl-avatar assistant" aria-hidden="true"><Sparkles size={14} /></span>
                  <div className="cpl-bubble-wrap">
                    <div className="cpl-bubble assistant cpl-thinking">
                      <span className="cpl-dots" aria-hidden="true">
                        <span className="typing-dot" />
                        <span className="typing-dot" />
                        <span className="typing-dot" />
                      </span>
                      <AIProcessingIndicator compact stage={copilotStage} />
                    </div>
                  </div>
                </div>
              )}
              <div ref={endRef} />
            </div>
          )}
        </div>

        {/* Composer */}
        <div className="cpl-composer">
          <div className="cpl-composer-inner">
            <div className="cpl-input-box">
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(); }
                }}
                placeholder={readOnly ? "Read-only on mobile — ask ARIA on desktop." : "Ask ARIA anything about your data..."}
                aria-label="Message ARIA Copilot"
                disabled={readOnly}
              />
              <button
                type="button"
                className="cpl-send"
                onClick={() => send()}
                disabled={!canSend}
                aria-label={pendingId ? "Waiting for ARIA's answer" : "Send question"}
                title={readOnly ? READ_ONLY_HINT : undefined}
              >
                <Send size={15} />
              </button>
            </div>
            <div className="cpl-composer-hint">
              <span className="keys">{pendingId ? "ARIA is working on your question…" : "Enter to send · Shift + Enter for a new line"}</span>
              {input.length > MAX_QUESTION - 500 && (
                <span className={tooLong ? "over" : undefined}>
                  {input.length.toLocaleString()} / {MAX_QUESTION.toLocaleString()}
                </span>
              )}
            </div>
            {readOnly && (
              <p className="cpl-readonly">Copilot is read-only on mobile — open ARIA on desktop to ask questions.</p>
            )}
          </div>
        </div>
      </section>

      {toDelete && (
        <ConfirmDialog
          title="Delete this conversation?"
          message={`“${toDelete.title || NEW_TITLE}” and its messages will be removed from this device.`}
          onConfirm={() => deleteConversation(toDelete.id)}
          onCancel={() => setToDelete(null)}
        />
      )}
    </div>
  );
}
