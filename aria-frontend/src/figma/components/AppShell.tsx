import { useState, useEffect } from "react";
import { useTheme } from "../App";
import type { Page } from "../App";
import {
  LayoutDashboard, Sparkles, Lightbulb, TrendingUp,
  Database, Bot, Clock, Settings, FileText,
  Sun, Moon, Menu, Compass,
  Search, LogOut, ChevronDown, Bell, CheckCheck, Trash2,
} from "lucide-react";
import { workspaceApi } from "../../services/api";

// The standalone Hypothesis page was removed: hypothesis is an investigation
// capability surfacing as Possible drivers inside AI Analytics / Insights /
// Forecast. Old #/hypothesis hashes alias to analytics.
const navGroups: { label: string; items: { id: Page; label: string; icon: React.ElementType }[] }[] = [
  {
    label: "Analytics",
    items: [
      { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
      { id: "analytics", label: "AI Analytics", icon: Sparkles },
      { id: "insights", label: "Insights", icon: Lightbulb },
      { id: "intelligence", label: "Intelligence", icon: Compass },
      { id: "predictive", label: "Forecast", icon: TrendingUp },
    ],
  },
  {
    label: "Data",
    items: [
      { id: "data", label: "Data", icon: Database },
      { id: "documents", label: "Documents", icon: FileText },
      { id: "copilot", label: "Copilot", icon: Bot },
    ],
  },
  {
    label: "System",
    items: [
      { id: "history", label: "History", icon: Clock },
      { id: "settings", label: "Settings", icon: Settings },
    ],
  },
];

const pageTitles: Record<Page, string> = {
  dashboard: "Dashboard",
  analytics: "AI Analytics",
  insights: "Insights",
  intelligence: "Intelligence",
  predictive: "Forecast",
  data: "Data",
  documents: "Documents",
  copilot: "Copilot",
  history: "History",
  settings: "Settings",
};

interface Props {
  children: React.ReactNode;
  user?: { email?: string } | null;
  selectedLLM?: string;
  dbName?: string;
  onChangeLLM?: () => void;
  onSignOut?: () => void;
}

export default function AppShell({ children, user, selectedLLM, dbName, onChangeLLM, onSignOut }: Props) {
  const { isDark, toggleTheme, page, setPage } = useTheme();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("aria_sidebar_collapsed") === "1";
    } catch {
      return false;
    }
  });
  const [profileOpen, setProfileOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifs, setNotifs] = useState<any[]>([]);

  useEffect(() => {
    try {
      localStorage.setItem("aria_sidebar_collapsed", collapsed ? "1" : "0");
    } catch { /* private mode: session-only */ }
  }, [collapsed]);

  /* Workspace notifications (monitor alerts etc.) — best-effort poll. */
  useEffect(() => {
    let dead = false;
    const tick = async () => {
      if (document.hidden) return;
      try {
        const r = await workspaceApi.listNotifications();
        if (!dead) setNotifs(Array.isArray(r?.data) ? r.data : []);
      } catch { /* the bell must never break the shell */ }
    };
    tick();
    const id = window.setInterval(tick, 60_000);
    return () => { dead = true; window.clearInterval(id); };
  }, []);

  const unread = notifs.reduce((n, x) => n + (x?.read ? 0 : 1), 0);

  const relTime = (iso: string) => {
    const t = Date.parse(iso);
    if (!Number.isFinite(t)) return "";
    const s = Math.max(0, (Date.now() - t) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
    return `${Math.floor(s / 86400)}d ago`;
  };

  const markAllRead = async () => {
    try {
      await workspaceApi.markNotificationsRead();
      setNotifs((ns) => ns.map((n) => ({ ...n, read: true })));
    } catch { /* noop */ }
  };

  const clearAllNotifs = async () => {
    try {
      await workspaceApi.clearNotifications();
      setNotifs([]);
    } catch { /* noop */ }
  };

  return (
    <div className="flex h-screen bg-background font-sans text-foreground overflow-hidden">
      {/* Sidebar */}
      <aside
        className="flex flex-col flex-shrink-0 border-r border-border/70 transition-all duration-300 ease-out h-full"
        style={{
          width: collapsed ? 68 : 232,
          background: "linear-gradient(180deg, var(--card) 0%, var(--card) 70%, var(--secondary)/40 100%)",
        }}
      >
        {/* Logo */}
        <div className="flex items-center h-16 px-4 gap-2.5 flex-shrink-0 overflow-hidden">
          <div
            className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center shadow-lg"
            style={{ background: "var(--gradient-primary)", boxShadow: "0 4px 14px -2px rgba(79,70,229,0.5)" }}
          >
            <Sparkles size={15} className="text-white" />
          </div>
          {!collapsed && (
            <div className="flex flex-col leading-none">
              <span className="font-bold text-[15px] text-foreground tracking-tight">ARIA</span>
              <span className="text-[9px] font-semibold text-primary/80 tracking-[0.18em] uppercase">Analytics</span>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-2 px-2.5 overflow-y-auto premium-scroll space-y-4">
          {navGroups.map((group) => (
            <div key={group.label}>
              {!collapsed && (
                <p className="px-3 mb-1 text-[10px] font-bold text-muted-foreground/70 uppercase tracking-[0.14em]">
                  {group.label}
                </p>
              )}
              <div className="space-y-0.5">
                {group.items.map(({ id, label, icon: Icon }) => {
                  const active = page === id;
                  return (
                    <button
                      key={id}
                      onClick={() => setPage(id)}
                      title={collapsed ? label : undefined}
                      aria-current={active ? "page" : undefined}
                      aria-label={label}
                      className={`relative w-full flex items-center gap-2.5 px-3 py-2 rounded-xl text-[13px] transition-all duration-200 ${
                        active
                          ? "bg-primary/10 text-primary font-semibold shadow-[inset_0_0_0_1px_rgba(79,70,229,0.15)]"
                          : "text-muted-foreground hover:text-foreground hover:bg-secondary/80"
                      } ${collapsed ? "justify-center px-0" : ""}`}
                    >
                      {active && !collapsed && (
                        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-1 h-5 rounded-r-full" style={{ background: "var(--gradient-primary)" }} />
                      )}
                      <Icon size={16} className="flex-shrink-0" strokeWidth={active ? 2.25 : 2} />
                      {!collapsed && <span className="truncate">{label}</span>}
                      {active && !collapsed && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-primary" />}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        {/* User */}
        <div className="p-2.5 flex-shrink-0">
          <div className={`flex items-center gap-2.5 rounded-xl bg-secondary/60 border border-border/60 px-2.5 py-2 overflow-hidden ${collapsed ? "justify-center px-0" : ""}`}>
            <div
              className="flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shadow-sm"
              style={{ background: "var(--gradient-primary)" }}
            >
              {user?.email?.[0]?.toUpperCase() || "A"}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold text-foreground truncate">{user?.email?.split("@")[0] || "User"}</p>
                <p className="text-[11px] text-muted-foreground truncate">{user?.email || "user@email.com"}</p>
              </div>
            )}
          </div>
        </div>

      </aside>

      {/* Main */}
      <div className="flex flex-col flex-1 min-w-0 h-full">
        {/* Topbar */}
        <header
          className="flex items-center h-14 px-5 border-b border-border bg-card/80 backdrop-blur-xl flex-shrink-0 gap-4 z-10"
          style={{ boxShadow: "0 1px 0 0 rgba(0,0,0,0.02), 0 1px 8px -4px rgba(0,0,0,0.04)" }}
        >
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="p-1.5 -ml-1 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all"
          >
            <Menu size={15} />
          </button>
          <div className="flex items-center gap-2 animate-fade-in">
            <h1 className="text-[15px] font-semibold text-foreground tracking-tight flex items-center gap-2">{pageTitles[page]}{dbName ? (
              <button
                onClick={() => setPage("data")}
                title={`Analyzing: ${dbName} — click to switch dataset`}
                aria-label={`Analyzing ${dbName}. Switch dataset`}
                className="inline-flex items-center gap-1 text-[11px] text-muted-foreground font-normal bg-secondary/70 border border-border/60 rounded-full px-2.5 py-0.5 hover:text-foreground hover:border-primary/50 transition-colors"
              >
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 inline-block" />
                {dbName}
              </button>
            ) : null}</h1>
          </div>

          <div className="flex-1" />

          {/* Search */}
          <button
            onClick={() => setPage("analytics")}
            aria-label="Search analyses"
            title="Ask ARIA"
            className="hidden md:flex items-center gap-2 px-3 h-8 rounded-lg bg-secondary/70 text-muted-foreground hover:text-foreground hover:bg-secondary text-[12.5px] transition-all border border-border/60 hover:border-border hover:shadow-sm">
            <Search size={12} />
            <span>Search...</span>
            <span className="ml-1.5 text-muted-foreground/60 text-[10px] font-mono bg-background/60 px-1.5 py-0.5 rounded border border-border/50">⌘K</span>
          </button>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
            className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all"
            title="Toggle theme"
          >
            {isDark ? <Sun size={14} /> : <Moon size={14} />}
          </button>

          {/* Notifications bell (monitor alerts from the workspace) */}
          <div className="relative">
            <button
              onClick={() => { setProfileOpen(false); setNotifOpen((o) => !o); }}
              aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
              className="relative p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all"
              title="Notifications"
            >
              <Bell size={14} />
              {unread > 0 && (
                <span className="absolute -top-0.5 -right-0.5 min-w-[14px] h-[14px] px-0.5 rounded-full bg-primary text-white text-[9px] font-bold flex items-center justify-center">
                  {unread > 9 ? "9+" : unread}
                </span>
              )}
            </button>
            {notifOpen && (
              <div
                className="absolute right-0 top-9 w-80 bg-card border border-border rounded-xl z-50 animate-scale-in overflow-hidden"
                style={{ boxShadow: "var(--shadow-xl)" }}
              >
                <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                  <p className="text-[12.5px] font-semibold text-foreground">Notifications</p>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={markAllRead}
                      disabled={!unread}
                      className="p-1 rounded-md hover:bg-secondary text-muted-foreground hover:text-foreground disabled:opacity-40"
                      title="Mark all read" aria-label="Mark all notifications read">
                      <CheckCheck size={13} />
                    </button>
                    <button
                      onClick={clearAllNotifs}
                      disabled={notifs.length === 0}
                      className="p-1 rounded-md hover:bg-secondary text-muted-foreground hover:text-negative disabled:opacity-40"
                      title="Clear all" aria-label="Clear all notifications">
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
                <div className="max-h-80 overflow-y-auto premium-scroll">
                  {notifs.length === 0 ? (
                    <p className="px-3 py-6 text-center text-[12px] text-muted-foreground">
                      Nothing yet. Monitors you create will alert you here.
                    </p>
                  ) : (
                    notifs.map((n) => (
                      <div key={String(n?.id || "")} className={`px-3 py-2.5 border-b border-border/60 last:border-0 ${n?.read ? "" : "bg-primary/5"}`}>
                        <div className="flex items-center gap-2 min-w-0">
                          {!n?.read && <span className="w-1.5 h-1.5 rounded-full bg-primary flex-shrink-0" aria-hidden />}
                          <p className="text-[12px] font-semibold text-foreground truncate flex-1">{String(n?.title || "Update")}</p>
                          <span className="text-[10px] text-muted-foreground flex-shrink-0">{relTime(String(n?.at || ""))}</span>
                        </div>
                        <p className="mt-0.5 text-[11.5px] text-muted-foreground leading-relaxed">{String(n?.message || "")}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Settings shortcut (was a dead Notifications bell with a dot) */}
          <button
            onClick={() => setPage("settings")}
            aria-label="Settings"
            className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all"
            title="Settings"
          >
            <Settings size={14} />
          </button>

          {/* Profile */}
          <div className="relative">
            <button
              onClick={() => { setNotifOpen(false); setProfileOpen((o) => !o); }}
              className="flex items-center gap-1.5 p-1 rounded-lg hover:bg-secondary transition-all"
            >
              <div
                className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold text-white"
                style={{ background: "var(--gradient-primary)" }}
              >
                {user?.email?.[0]?.toUpperCase() || "A"}
              </div>
              <ChevronDown size={10} className="text-muted-foreground" />
            </button>

            {profileOpen && (
              <div
                className="absolute right-0 top-9 w-48 bg-card border border-border rounded-xl py-1.5 z-50 animate-scale-in"
                style={{ boxShadow: "var(--shadow-xl)" }}
              >
                <div className="px-3 py-2.5 border-b border-border mb-1">
                  <p className="text-[12.5px] font-semibold text-foreground">{user?.email?.split("@")[0] || "User"}</p>
                  <p className="text-[11px] text-muted-foreground truncate">{user?.email || "user@email.com"}</p>
                </div>
                <button
                  onClick={() => { setPage("settings"); setProfileOpen(false); }}
                  className="w-full flex items-center gap-2 px-3 py-2 text-[12.5px] text-foreground hover:bg-secondary transition-colors"
                >
                  <Settings size={12} /> Settings
                </button>
                <div className="border-t border-border my-1" />
                <button
                  onClick={onSignOut}
                  className="w-full flex items-center gap-2 px-3 py-2 text-[12.5px] text-negative hover:bg-secondary transition-colors"
                >
                  <LogOut size={12} /> Sign out
                </button>
              </div>
            )}
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 overflow-auto page-bg">
          <div className="relative z-[1]">{children}</div>
        </main>
      </div>
    </div>
  );
}
