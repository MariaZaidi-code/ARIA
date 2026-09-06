import { Search, Bell, Sun, Moon, Menu } from "lucide-react";

const PAGE_META = {
  dashboard: { title: "Dashboard", sub: "Your business intelligence, at a glance." },
  askAria: { title: "Ask ARIA", sub: "Ask a business question about your data." },
  dataSource: { title: "Data Sources", sub: "Connect or upload your data." },
  schema: { title: "Schema", sub: "Explore your data structure." },
  history: { title: "History", sub: "Review previous analysis sessions." },
  savedReports: { title: "Reports", sub: "Access saved analyses." },
  documents: { title: "Documents", sub: "Manage uploaded documents." },
  insights: { title: "Insights", sub: "AI-powered business insights." },
  analytics: { title: "Analytics", sub: "Deep-dive analytics workspace." },
  predictions: { title: "Predictions", sub: "Forecasting and trends." },
  prescriptions: { title: "Prescriptions", sub: "Recommended actions." },
  hypothesis: { title: "Hypothesis", sub: "Test business hypotheses." },
  goals: { title: "Goal Agent", sub: "Goal-driven analysis." },
  copilot: { title: "Copilot", sub: "AI assistant." },
  settings: { title: "Settings", sub: "Configure ARIA." },
  help: { title: "Help & Support", sub: "Guides and support." },
};

function AppHeader({
  activePage,
  selectedLLM,
  currentUser,
  handleChangeLLM,
  handleSignOut,
  onNavigate,
  onOpenHistorySession,
  theme,
  setTheme,
  setMobileMenuOpen,
  dbConfigured,
}) {
  const meta = PAGE_META[activePage] || { title: "ARIA", sub: "" };
  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <header className="app-header">
      <div className="header-left">
        <button
          className="header-menu-btn"
          onClick={() => setMobileMenuOpen(true)}
        >
          <Menu size={20} />
        </button>
        <div className="header-title-group">
          <h1 className="header-title">{meta.title}</h1>
          <p className="header-subtitle">{meta.sub}</p>
        </div>
      </div>

      <div className="header-right">
        <div className="header-search">
          <Search size={15} />
          <input type="text" placeholder="Search for dashboards, reports, users..." />
        </div>

        {dbConfigured && (
          <div className="header-db-badge">
            <span className="header-db-dot" />
            Connected
          </div>
        )}

        <button className="header-icon-btn" title="Notifications">
          <Bell size={18} />
        </button>

        <button className="header-icon-btn" onClick={toggleTheme} title="Toggle theme">
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>

        <div className="header-user">
          <div className="header-avatar">
            {currentUser?.name?.charAt(0)?.toUpperCase() || "A"}
          </div>
          <div className="header-user-info">
            <span className="header-user-name">{currentUser?.name || "User"}</span>
            <span className="header-user-role">Admin</span>
          </div>
        </div>
      </div>
    </header>
  );
}

export default AppHeader;
