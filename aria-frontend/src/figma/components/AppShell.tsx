import { useState } from "react";
import { useTheme } from "../App";
import type { Page } from "../App";
import {
  LayoutDashboard, Sparkles, Lightbulb, TrendingUp, Target,
  FlaskConical, Database, Bot, Clock, Settings, FileText,
  ChevronLeft, ChevronRight, Bell, Sun, Moon,
  Search, LogOut, ChevronDown,
} from "lucide-react";

const navItems: { id: Page; label: string; icon: React.ElementType }[] = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "analytics", label: "AI Analytics", icon: Sparkles },
  { id: "insights", label: "Insights", icon: Lightbulb },
  { id: "predictive", label: "Predictive", icon: TrendingUp },
  { id: "prescription", label: "Prescription", icon: Target },
  { id: "hypothesis", label: "Hypothesis", icon: FlaskConical },
  { id: "data", label: "Data", icon: Database },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "copilot", label: "Copilot", icon: Bot },
  { id: "history", label: "History", icon: Clock },
  { id: "settings", label: "Settings", icon: Settings },
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
        className="flex flex-col flex-shrink-0 border-r border-border bg-card/95 backdrop-blur-md transition-all duration-300 ease-out h-full"
        style={{ width: collapsed ? 60 : 220, boxShadow: "1px 0 0 0 rgba(0,0,0,0.02)" }}
      >
        {/* Logo */}
        <div className="flex items-center h-14 px-4 border-b border-border gap-2.5 flex-shrink-0 overflow-hidden">
          <div
            className="flex-shrink-0 w-7 h-7 rounded-lg flex items-center justify-center shadow-md"
            style={{ background: "var(--gradient-primary)" }}
          >
            <Sparkles size={13} className="text-white" />
          </div>
          {!collapsed && (
            <div className="flex items-center gap-1.5">
              <span className="font-bold text-sm text-foreground tracking-tight">ARIA</span>
              <span className="badge-premium text-[8px]">AI</span>
            </div>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 py-2.5 overflow-y-auto premium-scroll">
          {navItems.map(({ id, label, icon: Icon }) => {
            const active = page === id;
            return (
              <button
                key={id}
                onClick={() => setPage(id)}
                title={collapsed ? label : undefined}
                className={`nav-item w-full flex items-center gap-2.5 px-4 py-2 my-0.5 text-[13px] transition-all duration-200 ${
                  active
                    ? "active font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary/60"
                }`}
              >
                <Icon size={15} className="flex-shrink-0" />
                {!collapsed && <span className="truncate">{label}</span>}
              </button>
            );
          })}
        </nav>

        {/* User */}
        <div className="border-t border-border px-3 py-2.5 flex-shrink-0 overflow-hidden">
          <div className={`flex items-center gap-2.5 ${collapsed ? "justify-center" : ""}`}>
            <div
              className="flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold text-white shadow-sm"
              style={{ background: "var(--gradient-primary)" }}
            >
              {user?.email?.[0]?.toUpperCase() || "A"}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-foreground truncate">{user?.email?.split("@")[0] || "User"}</p>
                <p className="text-[11px] text-muted-foreground truncate">{user?.email || "user@email.com"}</p>
              </div>
            )}
          </div>
        </div>

        {/* Collapse toggle */}
        <button
          onClick={() => setCollapsed((c) => !c)}
          className="border-t border-border flex items-center justify-center h-8 text-muted-foreground hover:text-foreground hover:bg-secondary/50 transition-colors flex-shrink-0"
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
          <button className="hidden md:flex items-center gap-2 px-3 h-8 rounded-lg bg-secondary/70 text-muted-foreground hover:text-foreground hover:bg-secondary text-[12.5px] transition-all border border-border/60 hover:border-border hover:shadow-sm">
            <Search size={12} />
            <span>Search...</span>
            <span className="ml-1.5 text-muted-foreground/60 text-[10px] font-mono bg-background/60 px-1.5 py-0.5 rounded border border-border/50">⌘K</span>
          </button>

          {/* Theme toggle */}
          <button
            onClick={toggleTheme}
            className="p-1.5 rounded-lg hover:bg-secondary text-muted-foreground hover:text-foreground transition-all"
            title="Toggle theme"
          >
            {isDark ? <Sun size={14} /> : <Moon size={14} />}
          </button>

          {/* Notifications */}
          <button
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
