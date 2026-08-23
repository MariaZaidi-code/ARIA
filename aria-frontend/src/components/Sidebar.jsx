function Sidebar({
  activePage,
  setActivePage,
  selectedLLM,
  currentUser,
  handleChangeLLM,
  handleSignOut,
}) {
  return (
    <aside className="sidebar">
      <div className="sidebar-top">
        {/* ================= ARIA BRANDING ================= */}
        <div>
          <h1 className="logo">ARIA</h1>

          <p className="logo-subtitle">Intelligent Analytics</p>

          <p className="selected-llm">
            {selectedLLM === "cloud" ? "Cloud LLM" : "Local LLM"}
          </p>
        </div>

        {/* ================= NAVIGATION ================= */}
        <nav className="nav-menu">
          <button
            className={`nav-item ${activePage === "dashboard" ? "active" : ""}`}
            onClick={() => setActivePage("dashboard")}
          >
            Dashboard
          </button>

          <button
            className={`nav-item ${activePage === "askAria" ? "active" : ""}`}
            onClick={() => setActivePage("askAria")}
          >
            Ask ARIA
          </button>

          <button
            className={`nav-item ${
              activePage === "dataSource" ? "active" : ""
            }`}
            onClick={() => setActivePage("dataSource")}
          >
            Data Sources
          </button>

          <button
            className={`nav-item ${activePage === "schema" ? "active" : ""}`}
            onClick={() => setActivePage("schema")}
          >
            Schema
          </button>

          <button
            className={`nav-item ${activePage === "history" ? "active" : ""}`}
            onClick={() => setActivePage("history")}
          >
            History
          </button>

          <button
            className={`nav-item ${
              activePage === "savedReports" ? "active" : ""
            }`}
            onClick={() => setActivePage("savedReports")}
          >
            Saved Reports
          </button>

          <button
            className={`nav-item ${activePage === "help" ? "active" : ""}`}
            onClick={() => setActivePage("help")}
          >
            Help & Support
          </button>
        </nav>
      </div>

      {/* ================= USER AREA ================= */}
      <div className="sidebar-user">
        <div className="sidebar-user-info">
          <span>Signed in as</span>

          <strong>{currentUser?.email || "ARIA User"}</strong>
        </div>

        <button className="change-llm-button" onClick={handleChangeLLM}>
          LLM Settings
        </button>

        <button className="signout-button" onClick={handleSignOut}>
          Sign Out
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
