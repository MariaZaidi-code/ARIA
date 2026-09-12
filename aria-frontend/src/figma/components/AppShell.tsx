import { useState } from "react";
import { useTheme } from "../App";
import type { Page } from "../App";
import {
  LayoutDashboard, Sparkles, Lightbulb, TrendingUp, Target,
  FlaskConical, Database, Bot, Clock, Settings, FileText,
  ChevronLeft, ChevronRight, Bell, Sun, Moon,
  Search, LogOut, ChevronDown,
} from "lucide-react";

const navGroups: { label: string; items: { id: Page; label: string; icon: React.ElementType }[] }[] = [
  {
    label: "Analytics",
    items: [
      { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
      { id: "analytics", label: "AI Analytics", icon: Sparkles },
      { id: "insights", label: "Insights", icon: Lightbulb },
      { id: "predictive", label: "Predictive", icon: TrendingUp },
      { id: "prescription", label: "Prescription", icon: Target },
      { id: "hypothesis", label: "Hypothesis", icon: FlaskConical },
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
  predictive: "Predictive Analysis",
  prescription: "Prescription",
  hypothesis: "Hypothesis",
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
  const [collapsed, setCollapsed] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);

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

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="mx-2.5 mb-2.5 flex items-center justify-center h-8 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary/70 transition-colors flex-shrink-0"
        >
          {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
        </button>
      </aside>

      {/* Main */}
      <div className="flex flex-col flex-1 min-w-0 h-full">
        {/* Topbar */}
        <header
          className="flex items-center h-14 px-5 border-b border-border bg-card/80 backdrop-blur-xl flex-shrink-0 gap-4 z-10"
          style={{ boxShadow: "0 1px 0 0 rgba(0,0,0,0.02), 0 1px 8px -4px rgba(0,0,0,0.04)" }}
        >
          <div className="flex items-center gap-2 animate-fade-in">
            <h1 className="text-[15px] font-semibold text-foreground tracking-tight flex items-center gap-2">{pageTitles[page]}{dbName ? <span className="text-[11px] text-muted-foreground font-normal">· {dbName}</span> : null}</h1>
          </div>

          <div className="flex-1" />

          {/* Search */}
          <button aria-label="Search analyses" className="hidden md:flex items-center gap-2 px-3 h-8 rounded-lg bg-secondary/70 text-muted-foreground hover:text-foreground hover:bg-secondary text-[12.5px] transition-all border border-border/60 hover:border-border hover:shadow-sm">
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

          {/* Notifications */}
          <button
            aria-label="Notifications"
            className="relative p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all"
            title="Notifications"
          >
            <Bell size={14} />
            <span className="absolute top-1 right-1 w-1.5 h-1.5 rounded-full bg-primary ring-2 ring-card" />
          </button>

          {/* Profile */}
          <div className="relative">
            <button
              onClick={() => setProfileOpen((o) => !o)}
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
