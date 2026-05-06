"""CSS for header, sidebar, and main content layout."""

CSS_LAYOUT = """
  .header { display: flex; justify-content: space-between; align-items: center; padding: 8px 20px; border-bottom: 1px solid var(--border); background: var(--card-bg); flex-shrink: 0; height: 52px; }
  .header h1 { font-size: 20px; font-weight: 600; letter-spacing: -0.5px; margin: 0; cursor: pointer; }
  .header h1:hover { color: var(--blue); }
  .header-actions { display: flex; gap: 8px; align-items: center; }
  #app-layout { display: flex; height: calc(100vh - 52px); overflow: hidden; }
  #exp-sidebar {
    width: 280px; min-width: 280px; border-right: 1px solid var(--border);
    display: flex; flex-direction: column; overflow: hidden;
    transition: width 0.2s ease, min-width 0.2s ease; flex-shrink: 0;
    background: var(--card-bg);
  }
  #exp-sidebar.collapsed { width: 44px; min-width: 44px; }
  #exp-sidebar.collapsed .sidebar-content { display: none; }
  #exp-sidebar.collapsed .collapse-strip { display: flex; }
  .sidebar-content { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
  .sidebar-header { display: flex; gap: 6px; padding: 10px 12px 8px; align-items: center; }
  .sidebar-header input { flex: 1; font-family: inherit; font-size: 14px; border: 1px solid var(--border); padding: 7px 10px; border-radius: 4px; background: var(--bg); min-width: 0; }
  .collapse-btn { font-family: inherit; font-size: 16px; background: none; border: 1px solid var(--border); padding: 4px 8px; cursor: pointer; border-radius: 3px; color: var(--muted); flex-shrink: 0; }
  .collapse-btn:hover { background: var(--code-bg); color: var(--fg); }
  .collapse-strip { display: none; flex-direction: column; align-items: center; padding-top: 12px; cursor: pointer; width: 44px; height: 100%; }
  .collapse-strip:hover { background: var(--code-bg); }
  .status-chips { display: flex; gap: 4px; padding: 6px 12px 8px; flex-wrap: wrap; }
  .status-chips button { font-family: inherit; font-size: 12px; background: var(--bg); border: 1px solid var(--border); padding: 3px 10px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .status-chips button:hover { background: var(--code-bg); color: var(--fg); }
  .status-chips button.active { background: var(--fg); color: var(--bg); }
  #exp-list { flex: 1; overflow-y: auto; padding: 0 8px 8px; }
  #main-content {
    flex: 1; overflow-y: auto; overflow-x: hidden; min-width: 0;
    padding: 16px 24px;
    container-type: inline-size; container-name: main;
  }
"""
