import { useEffect, useRef, useState } from "react";

import { getHistorySessions } from "../utils/historyStorage";

const PAGE_META = {
  dashboard: {
    title: "Dashboard",
    sub: "Your analytics command center at a glance.",
  },
  askAria: {
    title: "Ask ARIA",
    sub: "Ask a business question about your connected dataset.",
  },
  dataSource: {
    title: "Data Sources",
    sub: "Connect or upload the data that ARIA should analyze.",
  },
  schema: {
    title: "Schema",
    sub: "Explore the structure discovered by ARIA's Schema Agent.",
  },
  history: {
    title: "Analysis History",
    sub: "Review and reopen your previous ARIA analysis sessions.",
  },
  savedReports: {
    title: "Saved Reports",
    sub: "Access the ARIA analyses you saved for future review.",
  },
  documents: {
    title: "Documents",
    sub: "Manage your uploaded PDF documents.",
  },
  help: {
    title: "Help & Support",
    sub: "Get help using ARIA and understand the main analytics workflow.",
  },
};

const NAV_ITEMS = [
  { key: "dashboard", label: "Dashboard", hint: "Analytics command center" },
  { key: "askAria", label: "Ask ARIA", hint: "Ask business questions" },
  { key: "dataSource", label: "Data Sources", hint: "Connect or upload data" },
  { key: "schema", label: "Schema", hint: "Explore your data structure" },
  { key: "history", label: "Analysis History", hint: "Reopen past analyses" },
  { key: "savedReports", label: "Saved Reports", hint: "Reports you saved" },
  { key: "documents", label: "Documents", hint: "Manage PDF documents" },
  { key: "help", label: "Help & Support", hint: "Guides and support" },
];

function AppHeader({
  activePage,
  selectedLLM,
  currentUser,
  handleChangeLLM,
  handleSignOut,
  onNavigate,
  onOpenHistorySession,
}) {
  const [profileOpen, setProfileOpen] = useState(false);

  const [searchOpen, setSearchOpen] = useState(false);

  const [searchQuery, setSearchQuery] = useState("");

  const searchInputRef = useRef(null);

  const actionsRef = useRef(null);

  useEffect(() => {
    if (!profileOpen && !searchOpen) {
      return undefined;
    }

    const handleOutsideClick = (event) => {
      if (actionsRef.current && !actionsRef.current.contains(event.target)) {
        setProfileOpen(false);

        setSearchOpen(false);
      }
    };

    const handleKeyDown = (event) => {
      if (event.key === "Escape") {
        setProfileOpen(false);

        setSearchOpen(false);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);

    document.addEventListener("keydown", handleKeyDown);

    return () => {
      document.removeEventListener("mousedown", handleOutsideClick);

      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [profileOpen, searchOpen]);

  // Focus the search input the moment the panel opens.
  useEffect(() => {
    if (!searchOpen) {
      return undefined;
    }

    const focusTimer = setTimeout(() => searchInputRef.current?.focus(), 120);

    return () => clearTimeout(focusTimer);
  }, [searchOpen]);

  // Quick " / " shortcut to open global search from anywhere.
  useEffect(() => {
    const handleKeyDown = (event) => {
      if (event.key !== "/" || event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }

      const tag = (event.target?.tagName || "").toLowerCase();

      if (tag === "input" || tag === "textarea" || tag === "select") {
        return;
      }

      event.preventDefault();

      setSearchQuery("");

      setSearchOpen(true);
    };

    document.addEventListener("keydown", handleKeyDown);

    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  const searchSessions = getHistorySessions()
    .filter(
      (session) =>
        !currentUser?.email || session.userEmail === currentUser.email,
    )
    .sort((a, b) => new Date(b.createdAt || 0) - new Date(a.createdAt || 0))
    .slice(0, 6);

  const normalizedSearchQuery = searchQuery.trim().toLowerCase();

  const filteredNavItems = NAV_ITEMS.filter((item) => {
    if (!normalizedSearchQuery) {
      return true;
    }

    return (
      item.key.includes(normalizedSearchQuery) ||
      item.label.toLowerCase().includes(normalizedSearchQuery) ||
      item.hint.toLowerCase().includes(normalizedSearchQuery)
    );
  });

  const filteredSearchSessions = searchSessions.filter((session) => {
    if (!normalizedSearchQuery) {
      return true;
    }

    const searchableText = [
      session.question,
      session.source?.name,
      session.source?.type,
    ]
      .filter(Boolean)
      .map((value) => String(value).toLowerCase())
      .join(" ");

    return searchableText.includes(normalizedSearchQuery);
  });

  const meta = PAGE_META[activePage] || PAGE_META.dashboard;

  const userLabel = currentUser?.email || "ARIA User";

  const initials = userLabel
    .split(/[@\s._-]/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");

  return (
    <header className="app-header">
      <div className="app-header-crumbs">
        <span className="crumb-sep">✦</span>

        <span>ARIA</span>

        <span className="crumb-sep">/</span>

        <strong>{meta.title}</strong>
      </div>

      <div className="app-header-title-group">
        <h1 className="app-header-title">{meta.title}</h1>

        <p className="app-header-title-sub">{meta.sub}</p>
      </div>

      <div className="app-header-actions" ref={actionsRef}>
        <button
          type="button"
          className="app-icon-button"
          aria-label="Search ARIA"
          title="Search ( / )"
          onClick={() => {
            setSearchQuery("");

            setSearchOpen((open) => !open);
          }}
        >
          <span aria-hidden="true">⌕</span>
        </button>

        {searchOpen && (
          <div className="app-search-panel" role="dialog" aria-label="Search ARIA">
            <div className="app-search-input-wrap">
              <span className="app-search-panel-icon" aria-hidden="true">
                ⌕
              </span>

              <input
                ref={searchInputRef}
                type="text"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                placeholder="Search pages and analyses..."
              />

              <button
                type="button"
                className="app-search-escape"
                aria-label="Close search"
                onClick={() => setSearchOpen(false)}
              >
                Esc
              </button>
            </div>

            <div className="app-search-results">
              {filteredNavItems.length > 0 && (
                <div className="app-search-group">
                  <span className="app-search-group-label">Navigate</span>

                  {filteredNavItems.map((item) => (
                    <button
                      type="button"
                      className="app-search-item"
                      key={item.key}
                      onClick={() => {
                        setSearchQuery("");

                        setSearchOpen(false);

                        onNavigate(item.key);
                      }}
                    >
                      <span className="app-search-item-icon" aria-hidden="true">
                        ✦
                      </span>

                      <span className="app-search-item-text">
                        <strong>{item.label}</strong>

                        <small>{item.hint}</small>
                      </span>

                      {activePage === item.key && (
                        <span className="app-search-item-active">Current</span>
                      )}
                    </button>
                  ))}
                </div>
              )}

              {filteredSearchSessions.length > 0 && (
                <div className="app-search-group">
                  <span className="app-search-group-label">Recent analyses</span>

                  {filteredSearchSessions.map((session) => (
                    <button
                      type="button"
                      className="app-search-item"
                      key={session.id}
                      onClick={() => {
                        setSearchQuery("");

                        setSearchOpen(false);

                        onOpenHistorySession(session);
                      }}
                    >
                      <span className="app-search-item-icon" aria-hidden="true">
                        ↗
                      </span>

                      <span className="app-search-item-text">
                        <strong>{session.question}</strong>

                        <small>
                          {session.source?.name || "Analysis"} ·{" "}
                          {session.goal?.goalType || "General analysis"}
                        </small>
                      </span>
                    </button>
                  ))}
                </div>
              )}

              {filteredNavItems.length === 0 &&
                filteredSearchSessions.length === 0 && (
                  <div className="app-search-empty">
                    No results for “{searchQuery}”.
                  </div>
                )}
            </div>
          </div>
        )}

        <button
          type="button"
          className="app-chip"
          onClick={handleChangeLLM}
          title="AI engine"
        >
          <span className="sidebar-llm-dot" />

          {selectedLLM === "cloud"
            ? "Cloud LLM"
            : selectedLLM === "local"
              ? "Local LLM"
              : "AI Mode"}
        </button>

        <button
          type="button"
          className="app-icon-button"
          aria-label="Toggle theme"
          title={theme === "light" ? "Switch to dark theme" : "Switch to light theme"}
        >
          {theme === "dark" ? "☀" : "☾"}
        </button>

        <button
          type="button"
          className="app-icon-button"
          aria-label="Notifications"
          title="Notifications"
        >
          <span aria-hidden="true">🔔</span>

          <span className="app-bell-dot" />
        </button>

        <div className="app-profile">
          <button
            type="button"
            className="app-profile-button"
            onClick={() => setProfileOpen((open) => !open)}
            aria-haspopup="menu"
            aria-expanded={profileOpen}
          >
            <span className="app-profile-avatar">
              {initials || "AR".slice(0, 2)}
            </span>

            <span className="app-profile-name">{userLabel}</span>

            <span aria-hidden="true" style={{ fontSize: "11px", color: "#93a3c2" }}>
              ▾
            </span>
          </button>

          {profileOpen && (
            <div className="app-profile-menu" role="menu">
              <div className="app-profile-menu-head">
                <strong>{userLabel}</strong>

                <span>Signed in · {selectedLLM === "cloud" ? "Cloud LLM" : "Local LLM"}</span>
              </div>

              <button
                type="button"
                className="app-profile-menu-item"
                role="menuitem"
                onClick={() => {
                  setProfileOpen(false);

                  handleChangeLLM();
                }}
              >
                <span aria-hidden="true">⚙</span>

                LLM Settings
              </button>

              <button
                type="button"
                className="app-profile-menu-item danger"
                role="menuitem"
                onClick={() => {
                  setProfileOpen(false);

                  handleSignOut();
                }}
              >
                <span aria-hidden="true">↪</span>

                Sign Out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export default AppHeader;