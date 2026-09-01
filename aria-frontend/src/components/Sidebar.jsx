const NAV_ICONS = {
  dashboard: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="7" rx="1.6" />
      <rect x="14" y="3" width="7" height="7" rx="1.6" />
      <rect x="3" y="14" width="7" height="7" rx="1.6" />
      <rect x="14" y="14" width="7" height="7" rx="1.6" />
    </svg>
  ),
  askAria: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M15.5 4.5 17.2 8l3.5 1.7-3.5 1.7-1.7 3.5-1.7-3.5L8.3 9.7l3.5-1.7 1.4-2.6" />
      <path d="M7 16l1.2 2.4L10.6 19.6 8.2 20.8 7 23.2 5.8 20.8 3.4 19.6 5.8 18.4 7 16" />
    </svg>
  ),
  dataSource: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="8" ry="3" />
      <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5" />
      <path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    </svg>
  ),
  schema: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  ),
  history: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </svg>
  ),
  savedReports: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 3h12a1 1 0 0 1 1 1v17l-7-4.5L5 21V4a1 1 0 0 1 1-1z" />
      <path d="M9 8h6M9 12h4" />
    </svg>
  ),
  documents: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <polyline points="10 9 9 9 8 9" />
    </svg>
  ),
  help: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M9.2 9.2a2.9 2.9 0 0 1 5.6 1c0 1.9-2.8 2.3-2.8 3.8" />
      <path d="M12 17.4h.01" />
    </svg>
  ),
};

const NAV_SECTIONS = [
  {
    label: "Workspace",
    items: [
      { id: "dashboard", label: "Dashboard" },
      { id: "askAria", label: "Ask ARIA" },
      { id: "dataSource", label: "Data Sources" },
      { id: "schema", label: "Schema" },
    ],
  },
  {
    label: "Insights",
    items: [
      { id: "history", label: "History" },
      { id: "savedReports", label: "Saved Reports" },
      { id: "documents", label: "Documents" },
    ],
  },
  {
    label: "System",
    items: [{ id: "help", label: "Help & Support" }],
  },
];

function Sidebar({
  activePage,
  setActivePage,
  selectedLLM,
  currentUser,
  handleChangeLLM,
  handleSignOut,
}) {
  const userLabel = currentUser?.email || "ARIA User";

  const initials = userLabel
    .split(/[@\s._-]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  const llmLabel = selectedLLM === "cloud" ? "Cloud LLM" : "Local LLM";

  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        {/* ================= ARIA BRANDING ================= */}
        <div className="aria-brand-row">
          <span className="aria-brand-mark" aria-hidden="true">
            ✦
          </span>

          <div className="aria-brand-text">
            <h1 className="logo">ARIA</h1>

            <p className="logo-subtitle">Intelligent Analytics</p>
          </div>
        </div>

        <span className="sidebar-llm-pill">
          <span className="sidebar-llm-dot" />

          {llmLabel}
        </span>

        {/* ================= NAVIGATION ================= */}
        <nav className="nav-menu">
          {NAV_SECTIONS.map((section) => (
            <div key={section.label}>
              <span className="nav-section-label">{section.label}</span>

              {section.items.map((item) => (
                <button
                  key={item.id}
                  className={`nav-item ${activePage === item.id ? "active" : ""}`}
                  onClick={() => setActivePage(item.id)}
                >
                  <span className="nav-item-icon" aria-hidden="true">
                    {NAV_ICONS[item.id]}
                  </span>

                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </div>

      {/* ================= USER AREA ================= */}
      <div className="sidebar-user">
        <div className="sidebar-user-profile">
          <span className="sidebar-user-avatar" aria-hidden="true">
            {initials || "AR"}
          </span>

          <div className="sidebar-user-info">
            <span>Signed in as</span>

            <strong>{userLabel}</strong>
          </div>
        </div>

        <div className="sidebar-user-actions">
          <button className="change-llm-button" onClick={handleChangeLLM}>
            <span aria-hidden="true">⚙</span>

            <span>LLM Settings</span>
          </button>

          <button className="signout-button" onClick={handleSignOut}>
            Sign Out
          </button>
        </div>
      </div>
    </aside>
  );
}

export default Sidebar;