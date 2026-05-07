"""CSS for experiment cards, stats cards, and status indicators."""

CSS_CARDS = """
  .exp-card { padding: 10px 12px; border-radius: 4px; cursor: pointer; margin-bottom: 2px; border: 1px solid transparent; }
  .exp-card:hover { background: var(--code-bg); }
  .exp-card.active { background: rgba(44,90,160,0.08); border-color: var(--blue); }
  .exp-card-row1 { display: flex; align-items: center; gap: 6px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .status-dot.status-done { background: var(--green); }
  .status-dot.status-failed { background: var(--red); }
  .status-dot.status-running { background: var(--yellow); }
  .exp-card-name { flex: 1; min-width: 0; font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .exp-card-meta { font-size: 12px; color: var(--muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .exp-card-tags { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .exp-card-tags .tag { font-size: 12px; padding: 2px 6px; margin-left: 0; margin-right: 3px; }
  .exp-card-cb { margin-right: 4px; cursor: pointer; }
  .sidebar-study-header {
    display: flex; align-items: center; gap: 6px;
    padding: 6px 10px; margin: 4px 0 2px;
    background: var(--code-bg); border-radius: 4px;
    cursor: pointer; user-select: none;
    font-size: 12px; font-weight: 600;
    color: var(--fg);
  }
  .sidebar-study-header:hover { background: var(--border); }
  .sidebar-study-header.collapsed { opacity: 0.85; }
  .sidebar-study-toggle { font-size: 9px; color: var(--muted); width: 10px; flex-shrink: 0; }
  .sidebar-study-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .sidebar-study-count { color: var(--muted); font-weight: 500; font-size: 11px; padding: 1px 6px; background: var(--bg); border-radius: 8px; flex-shrink: 0; }
  #sidebar-group-study-btn.active { color: var(--blue); border-color: var(--blue); }
  .sidebar-actions-bar { padding: 8px 12px; border-top: 1px solid var(--border); background: var(--code-bg); display: flex; flex-direction: column; gap: 4px; }
  .sidebar-actions-bar button { font-family: inherit; font-size: 13px; border: none; padding: 6px 12px; cursor: pointer; border-radius: 3px; width: 100%; }
  .sidebar-actions-bar button.primary { background: var(--blue); color: #fff; }
  .sidebar-actions-bar button.export-btn { background: var(--card-bg); border: 1px solid var(--border); color: var(--fg); }
  .sidebar-actions-bar button.export-btn:hover { background: var(--border); }
  .sidebar-actions-bar button.danger { background: var(--card-bg); border: 1px solid var(--red); color: var(--red); }
  .sidebar-actions-bar button.danger:hover { background: var(--red); color: #fff; }
  .sidebar-actions-bar .action-count { font-size: 11px; color: var(--muted); text-align: center; }
  .stats { margin-bottom: 14px; }
  .stats-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 4px; font-weight: 600; }
  .stats-row { display: grid; gap: 8px; margin-bottom: 8px; }
  .stats-row.runs { grid-template-columns: repeat(4, 1fr); }
  .stats-row.additional { grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); }
  .stat {
    background: var(--card-bg); border: 1px solid var(--border);
    padding: 10px 12px; text-align: center; border-radius: 4px;
    position: relative;
  }
  .stat .num { font-size: 24px; font-weight: 600; }
  .stat .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-top: 2px; }
  .stat .stat-hint { display: none; position: absolute; bottom: -30px; left: 50%; transform: translateX(-50%); background: var(--fg); color: var(--bg); padding: 4px 10px; border-radius: 3px; font-size: 11px; white-space: nowrap; z-index: 10; }
  .stat:hover .stat-hint { display: block; }
  .status-done { color: var(--green); font-weight: 500; }
  .status-failed { color: var(--red); font-weight: 500; }
  .status-running { color: var(--yellow); font-weight: 500; }
"""
