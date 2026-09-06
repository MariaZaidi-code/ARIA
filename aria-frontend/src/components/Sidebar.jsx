import AriaLogo from "./AriaLogo";
import {
  LayoutDashboard,
  Database,
  Table2,
  Sparkles,
  GitBranch,
  TrendingUp,
  Pill,
  FlaskConical,
  MessageSquare,
  Bot,
  FileText,
  Settings,
  HelpCircle,
  LogOut,
  ChevronLeft,
  History,
} from "lucide-react";

const NAV_SECTIONS = [
  {
    label: "MAIN",
    items: [
      { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    ],
  },
  {
    label: "DATA",
    items: [
      { id: "dataSource", label: "Data Sources", icon: Database },
      { id: "schema", label: "Schema", icon: Table2 },
    ],
  },
  {
    label: "INTELLIGENCE",
    items: [
      { id: "askAria", label: "Ask ARIA", icon: MessageSquare },
      { id: "insights", label: "Insights", icon: Sparkles },
      { id: "analytics", label: "Analytics", icon: GitBranch },
      { id: "predictions", label: "Predictions", icon: TrendingUp },
      { id: "prescriptions", label: "Prescriptions", icon: Pill },
      { id: "hypothesis", label: "Hypothesis", icon: FlaskConical },
      { id: "copilot", label: "Copilot", icon: Bot },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      { id: "history", label: "History", icon: History },
      { id: "savedReports", label: "Reports", icon: FileText },
      { id: "settings", label: "Settings", icon: Settings },
      { id: "help", label: "Help", icon: HelpCircle },
    ],
  },
];

function Sidebar({
  activePage,
  setActivePage,
  selectedLLM,
  currentUser,
  handleChangeLLM,
  handleSignOut,
  collapsed,
  setCollapsed,
  mobileOpen,
  setMobileOpen,
}) {
  const handleNav = (id) => {
    setActivePage(id);
    setMobileOpen(false);
  };

  return (
    <>
      {mobileOpen && (
        <div className="sidebar-overlay" onClick={() => setMobileOpen(false)} />
      )}

      <aside
        className={`sidebar ${collapsed ? "sidebar--collapsed" : ""} ${
          mobileOpen ? "sidebar--open" : ""
        }`}
      >
        <div className="sidebar-header">
          <div className="sidebar-brand">
            <AriaLogo size={28} />
            {!collapsed && <span className="sidebar-brand-text">ARIA</span>}
          </div>
          <button
            className="sidebar-toggle"
            onClick={() => setCollapsed(!collapsed)}
            title={collapsed ? "Expand" : "Collapse"}
          >
            <ChevronLeft
              size={16}
              style={{ transform: collapsed ? "rotate(180deg)" : "none" }}
            />
          </button>
        </div>

        <nav className="sidebar-nav">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label} className="sidebar-section">
              {!collapsed && (
                <span className="sidebar-section-label">{section.label}</span>
              )}
              {section.items.map((item) => (
                <button
                  key={item.id}
                  className={`sidebar-item ${
                    activePage === item.id ? "sidebar-item--active" : ""
                  }`}
                  onClick={() => handleNav(item.id)}
                  title={collapsed ? item.label : undefined}
                >
                  <item.icon size={17} />
                  {!collapsed && <span>{item.label}</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-footer">
          {currentUser && (
            <div className="sidebar-user">
              <div className="sidebar-avatar">
                {currentUser.name?.charAt(0)?.toUpperCase() || "A"}
              </div>
              {!collapsed && (
                <div className="sidebar-user-info">
                  <span className="sidebar-user-name">{currentUser.name}</span>
                  <span className="sidebar-user-email">{currentUser.email}</span>
                </div>
              )}
            </div>
          )}

          <button
            className="sidebar-item sidebar-item--danger"
            onClick={handleSignOut}
            title={collapsed ? "Sign Out" : undefined}
          >
            <LogOut size={17} />
            {!collapsed && <span>Sign Out</span>}
          </button>
        </div>
      </aside>
    </>
  );
}

export default Sidebar;
