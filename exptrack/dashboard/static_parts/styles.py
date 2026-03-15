"""
exptrack/dashboard/static_parts/styles.py — All CSS styles

Split from static.py for maintainability. Each section is a separate constant.
"""

# CSS variables and reset
CSS_RESET = """
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap');
  * { margin: 0; padding: 0; box-sizing: border-box; }
  :root {
    --bg: #faf9f7; --fg: #1a1a1a; --muted: #777; --border: #d0d0d0;
    --green: #2d7d46; --red: #c0392b; --yellow: #b8860b; --blue: #2c5aa0;
    --purple: #7c3aed; --card-bg: #fff; --code-bg: #f5f3f0;
    --tl-cell: #2c5aa0; --tl-var: #7c3aed; --tl-artifact: #2d7d46;
    --tl-metric: #d4820f; --tl-obs: #999;
  }
  body.dark {
    --bg: #1a1a1a; --fg: #e0e0e0; --muted: #999; --border: #444;
    --green: #4caf50; --red: #ef5350; --yellow: #ffc107; --blue: #5c9ce6;
    --purple: #b388ff; --card-bg: #252525; --code-bg: #2d2d2d;
    --tl-cell: #5c9ce6; --tl-var: #b388ff; --tl-artifact: #4caf50;
    --tl-metric: #ffc107; --tl-obs: #777;
  }
  body {
    font-family: 'IBM Plex Mono', monospace;
    background: var(--bg); color: var(--fg);
    margin: 0; padding: 0;
    font-size: 15px; line-height: 1.5;
    overflow: hidden; height: 100vh;
  }
"""

# Layout: header, sidebar, main content
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
  #main-content { flex: 1; overflow-y: auto; min-width: 0; padding: 16px 24px; }
"""

# Cards: experiment cards, stats cards, status indicators
CSS_CARDS = """
  .exp-card { padding: 10px 12px; border-radius: 4px; cursor: pointer; margin-bottom: 2px; border: 1px solid transparent; }
  .exp-card:hover { background: var(--code-bg); }
  .exp-card.active { background: rgba(44,90,160,0.08); border-color: var(--blue); }
  .exp-card-row1 { display: flex; align-items: center; gap: 6px; }
  .status-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .status-dot.status-done { background: var(--green); }
  .status-dot.status-failed { background: var(--red); }
  .status-dot.status-running { background: var(--yellow); }
  .exp-card-name { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .exp-card-meta { font-size: 12px; color: var(--muted); margin-top: 2px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .exp-card-metrics { font-size: 12px; color: var(--blue); margin-top: 2px; }
  .exp-card-tags { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .exp-card-tags .tag { font-size: 12px; padding: 2px 6px; margin-left: 0; margin-right: 3px; }
  .exp-card-cb { margin-right: 4px; cursor: pointer; }
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

# Table, toolbar, actions
CSS_TABLE = """
  .table-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .toolbar-btn {
    font-family: inherit; font-size: 13px; padding: 7px 16px;
    border: 1px solid var(--border); background: var(--card-bg); cursor: pointer;
    color: var(--fg); white-space: nowrap; line-height: 1.4;
    transition: background 0.15s, border-color 0.15s;
  }
  .toolbar-btn:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); }
  .toolbar-btn:first-child { border-radius: 4px 0 0 4px; }
  .toolbar-btn:last-child { border-radius: 0 4px 4px 0; }
  .toolbar-btn:only-child { border-radius: 4px; }
  .toolbar-btn + .toolbar-btn { margin-left: -1px; }
  .toolbar-btn.active { background: var(--fg); color: var(--bg); border-color: var(--fg); }
  .toolbar-btn-group { display: inline-flex; }
  .toolbar-btn-group .toolbar-btn + .toolbar-btn { margin-left: -1px; }
  .toolbar-btn-group .toolbar-btn:first-child { border-radius: 4px 0 0 4px; }
  .toolbar-btn-group .toolbar-btn:last-child { border-radius: 0 4px 4px 0; }
  .toolbar-btn-group .toolbar-btn:only-child { border-radius: 4px; }
  .main-search-input {
    font-family: inherit; font-size: 14px; border: 1px solid var(--border);
    padding: 8px 14px; border-radius: 4px; background: var(--card-bg); min-width: 260px; color: var(--fg);
  }
  .main-search-input:focus { outline: none; border-color: var(--blue); }
  .table-actions-bar {
    display: flex; gap: 6px; align-items: center; padding: 8px 12px; margin-bottom: 8px;
    background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px;
  }
  .table-actions-bar .sel-count { font-size: 13px; color: var(--muted); margin-right: 4px; }
  .table-actions-bar button {
    font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 6px 14px;
    cursor: pointer; border-radius: 3px; background: var(--card-bg); color: var(--fg);
  }
  .table-actions-bar button:hover { background: var(--code-bg); }
  .table-actions-bar button.danger { background: var(--card-bg); color: var(--red); border-color: var(--red); }
  .table-actions-bar button.danger:hover { background: var(--red); color: #fff; }
  .table-actions-bar button.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .table-actions-bar button.primary:hover { opacity: 0.85; }
  .table-actions-bar button.deselect-btn { background: var(--card-bg); color: var(--fg); border-color: var(--border); font-weight: 500; }
  .table-actions-bar button.deselect-btn:hover { background: var(--border); }
  .highlight-toggle {
    display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--muted); margin-left: 4px;
  }
  .highlight-toggle label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; white-space: nowrap; }
  .highlight-toggle input[type="checkbox"] { accent-color: var(--purple); width: 16px; height: 16px; cursor: pointer; }
  .highlight-legend { display: inline-flex; gap: 6px; align-items: center; font-size: 12px; color: var(--muted); margin-left: 6px; }
  .highlight-legend-item { display: inline-flex; align-items: center; gap: 3px; }
  .highlight-legend-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  .cb-col { width: 36px; text-align: center; }
  .cb-col input { cursor: pointer; width: 16px; height: 16px; accent-color: var(--blue); }
  .exp-card-cb { accent-color: var(--blue); width: 15px; height: 15px; }
  tr td:nth-child(2) { padding: 10px 8px; }
  tr td:nth-child(2) input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--blue); }
  tr.highlighted-row { background: rgba(124,58,237,0.08); }
  tr.highlighted-row:hover { background: rgba(124,58,237,0.13); }
  tr.highlighted-row td:first-child { border-left: 3px solid var(--purple); }
  table { width: 100%; border-collapse: collapse; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; }
  th { text-align: left; padding: 12px 16px; border-bottom: 2px solid var(--fg); font-size: 13px; text-transform: uppercase; letter-spacing: 1px; user-select: none; }
  th.sortable { cursor: pointer; }
  th.sortable:hover { color: var(--blue); }
  th .sort-arrow { font-size: 10px; margin-left: 4px; opacity: 0.3; }
  th.sort-active .sort-arrow { opacity: 1; color: var(--blue); }
  td { padding: 10px 16px; border-bottom: 1px solid var(--border); font-size: 14px; }
  tr:hover { background: var(--code-bg); }
  tr.selected-row { background: rgba(44,90,160,0.08); }
  .tag { background: var(--code-bg); padding: 4px 10px; font-size: 14px; margin-left: 6px; border-radius: 3px; }
  .exp-metrics-preview { font-size: 13px; color: var(--muted); margin-top: 2px; }
  h2 { font-size: 14px; font-weight: 600; margin: 16px 0 8px; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); }
  h2 .help-icon { font-size: 13px; cursor: help; color: var(--blue); margin-left: 6px; font-weight: normal; text-transform: none; letter-spacing: 0; }
  .filters { margin-bottom: 18px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .filters button {
    font-family: inherit; font-size: 14px;
    background: var(--card-bg); border: 1px solid var(--border);
    padding: 6px 16px; cursor: pointer; border-radius: 3px;
  }
  .filters button:hover { background: var(--code-bg); }
  .filters button.active { background: var(--fg); color: var(--bg); }
  .filters .compare-selected {
    margin-left: auto; background: var(--blue); color: #fff; border: none;
    padding: 6px 16px; font-family: inherit; font-size: 14px; cursor: pointer;
    display: none; border-radius: 3px;
  }
  .filters .compare-selected.visible { display: inline-block; }
  .filters .search-box {
    font-family: inherit; font-size: 14px; border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 3px; background: var(--card-bg); min-width: 200px;
  }
"""

# Detail panel, info grid, params/metrics tables
CSS_DETAIL = """
  .detail-summary { display: flex; gap: 12px; flex-wrap: wrap; padding: 10px 14px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 12px; align-items: center; }
  .detail-summary .sum-item { font-size: 13px; color: var(--muted); }
  .detail-summary .sum-item strong { color: var(--fg); }
  .detail-summary .sum-sep { color: var(--border); }
  .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .detail-grid-full { grid-column: 1 / -1; }
  @media (max-width: 900px) {
    .detail-grid { grid-template-columns: 1fr; }
    #exp-sidebar { display: none; }
  }
  .detail { background: var(--card-bg); border: 1px solid var(--border); padding: 16px; margin-top: 12px; border-radius: 4px; }
  .detail-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; gap: 12px; flex-wrap: wrap; }
  .detail-export-bar { display: flex; align-items: flex-start; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .detail-header h2 { margin: 0; font-size: 16px; color: var(--fg); text-transform: none; letter-spacing: 0; }
  .detail-actions { display: flex; gap: 8px; flex-wrap: wrap; }
  .detail-actions button, .action-btn {
    font-family: inherit; font-size: 13px;
    background: var(--code-bg); border: 1px solid var(--border);
    padding: 6px 16px; cursor: pointer; border-radius: 4px;
  }
  .detail-actions button:hover, .action-btn:hover { background: var(--border); }
  .action-btn.danger { color: var(--red); border-color: var(--red); }
  .action-btn.danger:hover { background: var(--red); color: #fff; }
  .action-btn.primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .action-btn.primary:hover { opacity: 0.9; }
  .close-btn { cursor: pointer; font-size: 20px; background: none; border: none; font-family: inherit; padding: 4px 8px; }
  .close-btn:hover { background: var(--code-bg); border-radius: 3px; }
  .info-grid { display: grid; grid-template-columns: 160px 1fr; gap: 8px 20px; margin-bottom: 20px; font-size: 14px; }
  .info-grid .label { color: var(--muted); font-weight: 500; }
  .params-table, .metrics-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  .params-table td, .metrics-table td { padding: 8px 14px; border-bottom: 1px solid var(--border); font-size: 14px; }
  .params-table th, .metrics-table th { padding: 9px 14px; font-size: 13px; text-align: left; border-bottom: 2px solid var(--border); }
  .chart-container { max-width: 550px; margin: 12px 0; }
  .summary-card { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; border-radius: 4px; margin-bottom: 20px; }
  .summary-card .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .summary-card .summary-item { text-align: center; }
  .summary-card .summary-item .val { font-size: 18px; font-weight: 600; }
  .summary-card .summary-item .lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
"""

# Diff, code changes, variables
CSS_CODE = """
  .diff-view {
    background: var(--code-bg); padding: 16px; font-size: 13px;
    overflow-x: auto; max-height: 500px; overflow-y: auto;
    white-space: pre; border: 1px solid var(--border); border-radius: 4px;
  }
  .diff-add { color: var(--green); }
  .diff-del { color: var(--red); }
  .diff-hunk { color: var(--blue); font-weight: 600; }
  .code-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .code-changes .change-item { margin-bottom: 10px; }
  .code-changes .change-label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
  .code-changes .change-diff { white-space: pre-wrap; }
  .var-changes { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; margin-bottom: 20px; font-size: 13px; border-radius: 4px; }
  .var-changes table { width: 100%; table-layout: fixed; }
  .var-changes td { padding: 4px 8px; border-bottom: 1px solid var(--border); vertical-align: top; word-break: break-word; }
  .var-changes td:first-child { width: 30%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .var-changes .var-name { color: var(--blue); font-weight: 500; }
  .var-changes .var-type { color: var(--muted); font-size: 12px; }
  .var-section-title { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; margin: 10px 0 6px; }
"""

# Timeline
CSS_TIMELINE = """
  .timeline { padding: 0; margin: 16px 0; }
  .tl-event { display: flex; gap: 12px; padding: 8px 12px; border-left: 3px solid var(--border); margin-left: 8px; font-size: 13px; position: relative; }
  .tl-event:hover { background: var(--code-bg); }
  .tl-event.tl-cell_exec { border-left-color: var(--tl-cell); border-left-width: 4px; }
  .tl-event.tl-var_set { border-left-color: var(--tl-var); border-left-width: 4px; }
  .tl-event.tl-artifact { border-left-color: var(--tl-artifact); border-left-width: 4px; background: rgba(45,125,70,0.03); }
  .tl-event.tl-metric { border-left-color: var(--tl-metric); border-left-width: 4px; }
  .tl-event.tl-observational { border-left-color: var(--tl-obs); border-left-width: 2px; opacity: 0.6; }
  .tl-seq { color: var(--muted); min-width: 40px; font-size: 12px; }
  .tl-icon { min-width: 20px; text-align: center; font-weight: 600; }
  .tl-body { flex: 1; }
  .tl-code-preview { color: var(--muted); font-size: 12px; margin-top: 2px; white-space: pre-wrap; }
  .tl-diff { margin-top: 4px; font-size: 12px; }
  .tl-diff .diff-add { color: var(--green); }
  .tl-diff .diff-del { color: var(--red); }
  .tl-badge { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 3px; margin-left: 6px; }
  .tl-badge-new { background: #d4edda; color: #155724; }
  .tl-badge-edited { background: #fff3cd; color: #856404; }
  .tl-badge-rerun { background: var(--code-bg); color: var(--muted); }
  .tl-badge-output { background: #cce5ff; color: #004085; }
  .tl-var-arrow { color: var(--muted); }
  .tl-context { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .tl-filters { display: flex; gap: 6px; margin-bottom: 12px; flex-wrap: wrap; }
  .tl-filters button { font-family: inherit; font-size: 13px; background: var(--card-bg); border: 1px solid var(--border); padding: 5px 12px; cursor: pointer; border-radius: 4px; }
  .tl-filters button:hover { background: var(--code-bg); }
  .tl-filters button.active { background: var(--fg); color: var(--bg); }
  .tl-compare-bar { background: var(--code-bg); padding: 10px 14px; margin-bottom: 12px; border-radius: 4px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 13px; }
  .tl-compare-bar button { font-family: inherit; font-size: 13px; background: var(--blue); color: #fff; border: none; padding: 6px 14px; cursor: pointer; border-radius: 4px; }
  .tl-seq-select { cursor: pointer; }
  .tl-seq-select:hover { background: rgba(44,90,160,0.1); }
  .tl-seq-select.selected { background: rgba(44,90,160,0.15); outline: 2px solid var(--blue); }
  .within-compare { background: var(--card-bg); border: 1px solid var(--border); padding: 20px; border-radius: 4px; margin-top: 16px; }
  .within-compare h3 { font-size: 14px; margin-bottom: 12px; }
  .source-view { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; font-size: 13px; border-radius: 4px; white-space: pre-wrap; max-height: 500px; overflow-y: auto; margin-top: 6px; }
  .source-view .line-num { color: var(--muted); display: inline-block; min-width: 30px; text-align: right; margin-right: 12px; user-select: none; }
  .view-source-btn { font-family: inherit; font-size: 12px; padding: 3px 10px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; margin-left: 6px; color: var(--blue); }
  .view-source-btn:hover { background: var(--code-bg); }
  .tl-type-label { display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 3px; margin-right: 6px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
  .tl-type-label.tl-type-cell_exec { background: rgba(44,90,160,0.12); color: var(--tl-cell); }
  .tl-type-label.tl-type-var_set { background: rgba(124,58,237,0.12); color: var(--tl-var); }
  .tl-type-label.tl-type-artifact { background: rgba(45,125,70,0.12); color: var(--tl-artifact); }
  .tl-type-label.tl-type-metric { background: rgba(212,130,15,0.12); color: var(--tl-metric); }
  .tl-type-label.tl-type-observational { background: rgba(153,153,153,0.12); color: var(--tl-obs); }
"""

# Compare view
CSS_COMPARE = """
  .compare-main-btn { font-family: inherit; font-size: 13px; padding: 7px 16px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; color: var(--fg); white-space: nowrap; transition: background 0.15s, border-color 0.15s; border-radius: 4px; }
  .compare-main-btn:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); }
  .compare-header { margin-bottom: 12px; }
  .compare-header h3 { font-size: 18px; }
  .back-link { font-family: inherit; font-size: 14px; background: none; border: none; color: var(--blue); cursor: pointer; padding: 2px 0; }
  .back-link:hover { text-decoration: underline; }
  .compare-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
  .compare-input { display: flex; gap: 10px; margin-bottom: 20px; align-items: flex-end; flex-wrap: wrap; }
  .compare-selector { display: flex; flex-direction: column; gap: 4px; }
  .compare-label { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--muted); }
  .compare-input select, .compare-input input {
    font-family: inherit; font-size: 14px;
    border: 1px solid var(--border); padding: 8px 14px; min-width: 260px;
    background: var(--card-bg); border-radius: 4px;
  }
  .compare-input button {
    font-family: inherit; font-size: 14px;
    background: var(--fg); color: var(--bg); border: none;
    padding: 8px 18px; cursor: pointer; border-radius: 4px;
  }
  .compare-input button.primary { background: var(--blue); color: #fff; }
  .compare-input .vs-label { font-weight: 600; color: var(--muted); font-size: 16px; padding-bottom: 6px; }
  .differs { color: var(--yellow); font-weight: 600; }
  .diff-added { color: var(--green, #3fb950); background: rgba(63,185,80,0.1); }
  .diff-removed { color: var(--red, #f85149); background: rgba(248,81,73,0.1); }
  .only-differs-toggle { font-family: inherit; font-size: 13px; margin-left: 12px; cursor: pointer; }
"""

# UI components: tabs, help, export, tags, inline editing, artifacts, owl
CSS_COMPONENTS = """
  .help-btn {
    font-family: inherit; font-size: 13px; background: var(--code-bg);
    border: 1px solid var(--border); padding: 6px 12px; cursor: pointer;
    border-radius: 4px; color: var(--muted);
  }
  .help-btn:hover { background: var(--border); color: var(--fg); }
  .theme-btn { font-family: inherit; font-size: 18px; background: var(--code-bg); border: 1px solid var(--border); padding: 5px 12px; cursor: pointer; border-radius: 4px; color: var(--muted); line-height: 1; }
  .theme-btn:hover { background: var(--border); color: var(--fg); }
  .tabs { display: flex; gap: 0; margin-bottom: 20px; border-bottom: 2px solid var(--border); }
  .tab {
    font-family: inherit; font-size: 14px;
    background: none; border: none; padding: 11px 22px;
    cursor: pointer; text-transform: uppercase; letter-spacing: 1px;
    border-bottom: 2px solid transparent; margin-bottom: -2px;
  }
  .tab:hover { background: var(--code-bg); }
  .tab.active { border-bottom-color: var(--fg); font-weight: 600; }
  #view { min-height: 200px; }
  .inline-form { display: inline-flex; gap: 6px; align-items: center; margin-left: 8px; }
  .inline-form input {
    font-family: inherit; font-size: 14px; border: 1px solid var(--border);
    padding: 5px 10px; border-radius: 4px; background: var(--card-bg);
  }
  .inline-form button {
    font-family: inherit; font-size: 13px; padding: 5px 12px;
    border: 1px solid var(--border); background: var(--code-bg);
    cursor: pointer; border-radius: 4px;
  }
  .inline-form button:hover { background: var(--border); }
  .notes-display { white-space: pre-wrap; background: var(--code-bg); padding: 12px; border-radius: 4px; margin: 4px 0; font-size: 14px; position: relative; }
  .notes-edit-btn { position: absolute; top: 6px; right: 6px; font-size: 12px; cursor: pointer; color: var(--muted); background: var(--card-bg); border: 1px solid var(--border); padding: 3px 8px; border-radius: 3px; }
  .notes-edit-btn:hover { color: var(--blue); border-color: var(--blue); }
  .notes-edit-area { width: 100%; font-family: inherit; font-size: 14px; border: 1px solid var(--blue); padding: 10px; border-radius: 4px; background: var(--card-bg); min-height: 90px; resize: vertical; }
  .tag-list { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .tag-removable { background: var(--code-bg); padding: 5px 12px; font-size: 14px; border-radius: 4px; display: inline-flex; align-items: center; gap: 5px; cursor: default; }
  .tag-removable .tag-delete { cursor: pointer; color: var(--muted); font-size: 16px; margin-left: 4px; line-height: 1; opacity: 0.6; }
  .tag-removable:hover .tag-delete { opacity: 1; color: var(--red, #e55); }
  .tag-removable .tag-delete:hover { opacity: 1; color: var(--red, #e55); }
  .tag-removable .tag-edit { cursor: pointer; color: var(--muted); font-size: 12px; }
  .tag-removable .tag-edit:hover { color: var(--blue); }
  .manage-tags-link {
    font-family: inherit; font-size: 13px; padding: 7px 16px;
    border: 1px solid var(--border); background: var(--card-bg); cursor: pointer;
    color: var(--fg); white-space: nowrap; border-radius: 0 4px 4px 0;
    transition: background 0.15s, border-color 0.15s; margin-left: -1px;
  }
  .manage-tags-link:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); text-decoration: none; }
  .manage-drawer-overlay {
    position: fixed; top: 0; left: 0; right: 0; bottom: 0;
    background: rgba(0,0,0,0.3); z-index: 999;
    opacity: 0; pointer-events: none; transition: opacity 0.2s;
  }
  .manage-drawer-overlay.visible { opacity: 1; pointer-events: auto; }
  .manage-drawer {
    position: fixed; top: 0; right: -360px; bottom: 0; width: 340px;
    background: var(--card-bg); border-left: 1px solid var(--border);
    box-shadow: -4px 0 20px rgba(0,0,0,0.12); z-index: 1000;
    display: flex; flex-direction: column;
    transition: right 0.25s ease;
  }
  .manage-drawer.visible { right: 0; }
  .manage-drawer-header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 16px 20px; border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .manage-drawer-header h3 { font-size: 15px; font-weight: 600; margin: 0; }
  .manage-drawer-close {
    background: none; border: none; font-size: 20px; cursor: pointer;
    color: var(--muted); padding: 4px 8px; border-radius: 3px; font-family: inherit;
  }
  .manage-drawer-close:hover { background: var(--code-bg); color: var(--fg); }
  .manage-drawer-body { flex: 1; overflow-y: auto; padding: 16px 20px; }
  .manage-section { margin-bottom: 20px; }
  .manage-section h4 {
    font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px;
    color: var(--muted); margin-bottom: 8px; padding-bottom: 6px; border-bottom: 1px solid var(--border);
  }
  .tag-manager-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 8px 10px; border-radius: 3px; margin-bottom: 2px;
    transition: background 0.1s;
  }
  .tag-manager-row:hover { background: var(--code-bg); }
  .tag-manager-row .tm-name { color: var(--blue); }
  .tag-manager-row .tm-count { color: var(--muted); font-size: 13px; margin-left: 8px; }
  .tag-manager-row .tm-delete {
    cursor: pointer; color: var(--muted); font-size: 14px; padding: 2px 6px;
    border-radius: 3px; opacity: 0; transition: opacity 0.1s;
  }
  .tag-manager-row:hover .tm-delete { opacity: 1; }
  .tag-manager-row .tm-delete:hover { color: var(--red); background: rgba(192,57,43,0.1); }
  .artifact-row { display: flex; align-items: center; gap: 8px; }
  .artifact-type-badge { font-size: 11px; padding: 1px 6px; border-radius: 3px; background: var(--code-bg); color: var(--muted); }
  .artifact-type-badge.img { background: #d4edda; color: #155724; }
  .artifact-type-badge.model { background: #cce5ff; color: #004085; }
  .artifact-type-badge.data { background: #fff3cd; color: #856404; }
  .artifact-add-form { display: flex; gap: 8px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
  .artifact-add-form input { font-family: inherit; font-size: 14px; border: 1px solid var(--border); padding: 6px 10px; border-radius: 4px; background: var(--card-bg); }
  .artifact-add-form button { font-family: inherit; font-size: 13px; padding: 6px 14px; border: 1px solid var(--border); background: var(--code-bg); cursor: pointer; border-radius: 4px; }
  .artifact-actions { display: flex; gap: 4px; }
  .artifact-actions button { font-family: inherit; font-size: 12px; padding: 3px 8px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; color: var(--muted); }
  .artifact-actions button:hover { color: var(--fg); border-color: var(--fg); }
  .artifact-actions button.art-del:hover { color: var(--red); border-color: var(--red); }
  .home-btn { font-family: inherit; font-size: 13px; background: var(--code-bg); border: 1px solid var(--border); padding: 6px 14px; cursor: pointer; border-radius: 4px; color: var(--muted); }
  .home-btn:hover { background: var(--border); color: var(--fg); }
  .help-panel { display: none; background: var(--card-bg); border: 1px solid var(--border); padding: 24px; border-radius: 4px; margin-bottom: 20px; }
  .help-panel.visible { display: block; }
  .help-panel h3 { font-size: 15px; margin: 16px 0 8px; }
  .help-panel h3:first-child { margin-top: 0; }
  .help-panel p { color: var(--muted); font-size: 13px; margin-bottom: 8px; line-height: 1.5; }
  .help-panel .help-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 12px 0; }
  .help-panel .help-item { background: var(--code-bg); padding: 12px; border-radius: 4px; }
  .help-panel .help-item strong { display: block; margin-bottom: 4px; font-size: 13px; }
  .help-panel .help-item span { font-size: 12px; color: var(--muted); }
  .help-close { float: right; cursor: pointer; font-size: 18px; background: none; border: none; font-family: inherit; color: var(--muted); }
  .help-close:hover { color: var(--fg); }
  .export-panel { background: var(--card-bg); border: 1px solid var(--border); padding: 16px; border-radius: 6px; margin-top: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); position: relative; z-index: 10; }
  .export-panel pre { white-space: pre-wrap; font-size: 12px; max-height: 400px; overflow-y: auto; background: var(--code-bg); padding: 12px; border-radius: 4px; border: 1px solid var(--border); }
  .export-panel .export-actions { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .export-panel .export-actions .action-btn.active-fmt { background: var(--blue); color: #fff; border-color: var(--blue); }
  .export-dropdown-menu { position: absolute; bottom: 100%; left: 0; background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px; padding: 4px; z-index: 100; min-width: 110px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); }
  .export-dropdown-menu button { display: block; width: 100%; text-align: left; margin: 2px 0; }
  .tooltip { position: relative; display: inline-block; }
  .tooltip .tooltip-text {
    visibility: hidden; background: var(--fg); color: var(--bg);
    text-align: center; border-radius: 3px; padding: 5px 10px;
    position: absolute; z-index: 1; bottom: 125%; left: 50%;
    transform: translateX(-50%); font-size: 11px; white-space: nowrap;
  }
  .tooltip:hover .tooltip-text { visibility: visible; }
  .bulk-bar { display: flex; gap: 8px; align-items: center; padding: 8px 16px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 12px; }
  .bulk-bar .bulk-count { font-weight: 600; }
  .bulk-bar button { font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 6px 14px; cursor: pointer; border-radius: 4px; background: var(--card-bg); }
  .bulk-bar button.danger { color: var(--red); border-color: var(--red); }
  .bulk-bar button.danger:hover { background: var(--red); color: #fff; }
  .section-toggle {
    cursor: pointer; user-select: none; display: flex; align-items: center; gap: 8px;
    padding: 6px 0; border-radius: 3px;
  }
  .section-toggle:hover { color: var(--blue); }
  .section-toggle::before {
    content: '\\25BC'; font-size: 10px; transition: transform 0.15s; display: inline-block; width: 14px; text-align: center;
  }
  .section-toggle.collapsed::before { transform: rotate(-90deg); }
  .section-body { transition: max-height 0.2s ease; }
  .section-toggle.collapsed + .section-body { display: none; }
  .editable-cell { cursor: default; padding: 5px 8px; border-radius: 3px; position: relative; min-height: 32px; }
  .editable-cell:hover { background: rgba(44,90,160,0.08); }
  .edit-icon { display: none; font-size: 11px; color: var(--muted); margin-left: 4px; vertical-align: middle; }
  .editable-cell:hover .edit-icon { display: inline; }
  .col-resizer {
    position: absolute; right: -3px; top: 0; width: 7px; height: 100%;
    cursor: col-resize; z-index: 2;
    border-right: 2px solid var(--border);
  }
  .col-resizer:hover, .col-resizer:active { border-right-color: var(--blue); background: rgba(44,90,160,0.10); }
  .col-settings-bar { display: flex; justify-content: flex-end; margin-bottom: 4px; position: relative; }
  .col-settings-btn {
    font-family: inherit; font-size: 13px; background: var(--code-bg); border: 1px solid var(--border);
    padding: 6px 12px; cursor: pointer; border-radius: 4px; color: var(--muted);
  }
  .col-settings-btn:hover { color: var(--fg); border-color: var(--fg); }
  .col-settings-panel {
    display: none; position: absolute; top: 100%; right: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); min-width: 160px;
  }
  .col-settings-list { display: flex; flex-direction: column; gap: 4px; }
  .col-setting-item { display: flex; align-items: center; gap: 8px; font-size: 13px; cursor: pointer; padding: 4px 0; }
  .col-setting-item:hover { color: var(--blue); }
  .col-setting-item input { cursor: pointer; accent-color: var(--blue); }
  .col-reset-btn {
    font-family: inherit; font-size: 12px; width: 100%; padding: 5px 10px;
    border: 1px solid var(--border); background: var(--code-bg); cursor: pointer;
    border-radius: 3px; color: var(--muted);
  }
  .col-reset-btn:hover { background: var(--border); color: var(--fg); }
  .table-scroll-wrap { overflow-x: auto; overflow-y: visible; }
  #exp-table { table-layout: fixed; min-width: 100%; }
  #exp-table th { position: relative; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  #exp-table td { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 0; }
  .name-edit-input { font-family: inherit; font-size: 14px; border: 1px solid var(--blue); padding: 5px 8px; border-radius: 4px; background: var(--card-bg); width: 100%; max-width: 300px; }
  .notes-cell { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--muted); }
  .tags-cell .tag { font-size: 13px; padding: 3px 8px; }
  .pin-btn { cursor: pointer; font-size: 14px; background: none; border: none; color: var(--muted); padding: 0 2px; }
  .pin-btn:hover { color: var(--yellow); }
  .pin-btn.pinned { color: var(--yellow); }
  .pinned-row { background: rgba(184,134,11,0.05); }
  .pinned-row:hover { background: rgba(184,134,11,0.1); }
  #exp-body tr { cursor: pointer; }
  #exp-body tr:hover { background: var(--code-bg); }
  .tag-filter-bar { display: inline-flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .tag-filter-bar .tag-chip {
    font-family: inherit; font-size: 13px; background: var(--card-bg); border: 1px solid var(--border);
    padding: 5px 12px; cursor: pointer; border-radius: 3px; color: var(--muted);
    transition: background 0.15s, border-color 0.15s;
  }
  .tag-filter-bar .tag-chip:hover { background: var(--code-bg); border-color: var(--blue); color: var(--blue); }
  .tag-filter-bar .tag-chip.active { background: var(--blue); color: #fff; border-color: var(--blue); }
  .tag-delete-x { position:absolute; right:3px; top:50%; transform:translateY(-50%); font-size:12px; opacity:0; cursor:pointer; color:var(--red,#e55); line-height:1; }
  .tag-chip:hover .tag-delete-x { opacity:0.7; }
  .tag-delete-x:hover { opacity:1 !important; }
  .group-bar { display: flex; gap: 4px; align-items: center; margin-bottom: 10px; font-size: 12px; color: var(--muted); }
  .group-bar button { font-family: inherit; font-size: 12px; background: var(--code-bg); border: 1px solid var(--border); padding: 4px 10px; cursor: pointer; border-radius: 3px; color: var(--muted); }
  .group-bar button:hover { background: var(--border); color: var(--fg); }
  .group-bar button.active { background: var(--fg); color: var(--bg); }
  .group-header td { background: var(--code-bg); font-size: 12px; font-weight: 600; padding: 8px 16px; cursor: pointer; user-select: none; border-bottom: 2px solid var(--border); }
  .group-header td:hover { background: var(--border); }
  .group-header .group-label { color: var(--fg); }
  .group-header .group-meta { color: var(--muted); font-weight: 400; margin-left: 8px; }
  .group-header .group-toggle { float: right; color: var(--muted); font-size: 10px; }
  .code-stat { font-size: 11px; color: var(--muted); }
  .code-stat .lines-added { color: var(--green); }
  .code-stat .lines-removed { color: var(--red); }
  .notes-cell-expanded { max-width: 250px; font-size: 12px; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  #detail-name { cursor: default; padding: 2px 6px; border-radius: 3px; }
  #detail-name:hover { background: rgba(44,90,160,0.08); }
  .tag-autocomplete { position: relative; display: inline-block; }
  .tag-autocomplete-list {
    position: absolute; top: 100%; left: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px;
    max-height: 180px; overflow-y: auto; min-width: 160px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  .tag-autocomplete-item {
    padding: 6px 12px; cursor: pointer; font-size: 13px; display: flex; justify-content: space-between;
  }
  .tag-autocomplete-item:hover, .tag-autocomplete-item.active { background: var(--code-bg); color: var(--blue); }
  .tag-autocomplete-item .tag-count { color: var(--muted); font-size: 11px; }
  .tag-autocomplete-new { color: var(--green); font-style: italic; }
  .editable-hint { border-bottom: 1px dashed transparent; transition: border-color 0.15s; }
  .editable-hint:hover { border-bottom-color: var(--blue); }
  .detail-tags-inline { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
  .detail-tags-inline .tag-input-area { display: inline-flex; align-items: center; }
  .detail-notes-inline { cursor: text; min-height: 28px; padding: 6px; border-radius: 4px; }
  .detail-notes-inline:hover { background: rgba(44,90,160,0.05); }
  .owl-mascot { cursor: pointer; transition: transform 0.3s; display: inline-block; }
  .owl-mascot:hover { transform: scale(1.2) rotate(-5deg); }
  .owl-mascot:active { transform: scale(0.95); }
  .owl-mascot.owl-blink svg rect.owl-eye-white { animation: owlBlink 3s infinite; }
  .owl-mascot.owl-bounce { animation: owlBounce 0.5s ease; }
  .owl-mascot.owl-wiggle { animation: owlWiggle 0.4s ease; }
  @keyframes owlBlink { 0%,92%,100% { height: 1; } 94%,98% { height: 0; } }
  @keyframes owlBounce { 0%,100% { transform: translateY(0); } 40% { transform: translateY(-8px); } 60% { transform: translateY(-4px); } }
  @keyframes owlWiggle { 0%,100% { transform: rotate(0deg); } 25% { transform: rotate(-8deg); } 75% { transform: rotate(8deg); } }
  .owl-speech { position: absolute; background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 11px; color: var(--fg); white-space: nowrap; box-shadow: 0 2px 8px rgba(0,0,0,0.1); z-index: 100; bottom: 40px; left: 50%; transform: translateX(-50%); pointer-events: none; opacity: 0; transition: opacity 0.3s; }
  .owl-speech.visible { opacity: 1; }
  .owl-speech::after { content: ''; position: absolute; top: 100%; left: 50%; margin-left: -5px; border: 5px solid transparent; border-top-color: var(--border); }
  .owl-container { position: relative; display: inline-block; }
  .tz-setting { display: inline-flex; align-items: center; gap: 6px; }
  .tz-setting select { font-family: inherit; font-size: 12px; border: 1px solid var(--border); padding: 5px 10px; border-radius: 4px; background: var(--code-bg); color: var(--muted); cursor: pointer; }
  .tz-setting select:hover { background: var(--border); color: var(--fg); }
"""

# Study management panel
CSS_STUDIES = """
  .study-panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; padding: 16px; margin-bottom: 16px; }
  .study-panel h3 { font-size: 14px; margin-bottom: 12px; }
  .study-card { display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border: 1px solid var(--border); border-radius: 4px; margin-bottom: 4px; }
  .study-card:hover { background: var(--code-bg); }
  .study-card-name { font-weight: 600; font-size: 14px; color: var(--blue); cursor: pointer; }
  .study-card-meta { font-size: 13px; color: var(--muted); }
  .study-card-actions { display: flex; gap: 6px; }
  .study-card-actions button { font-family: inherit; font-size: 12px; padding: 4px 10px; border: 1px solid var(--border); background: var(--card-bg); cursor: pointer; border-radius: 3px; }
  .study-card-actions button.danger:hover { color: var(--red); border-color: var(--red); }
  .study-create-form { display: flex; gap: 8px; margin-top: 8px; }
  .study-create-form input { font-family: inherit; font-size: 14px; border: 1px solid var(--border); padding: 6px 10px; border-radius: 4px; background: var(--card-bg); flex: 1; }
  .study-create-form button { font-family: inherit; font-size: 13px; padding: 6px 14px; border: none; background: var(--blue); color: #fff; cursor: pointer; border-radius: 4px; }
"""


# Image gallery
CSS_IMAGES = """
  .img-gallery-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; flex-wrap: wrap; }
  .img-filter-select { font-family: inherit; font-size: 12px; padding: 3px 8px; border: 1px solid var(--border); border-radius: 3px; background: var(--card-bg); color: var(--fg); }
  .img-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .img-card { border: 1px solid var(--border); border-radius: 6px; overflow: hidden; cursor: pointer; background: var(--card-bg); transition: box-shadow 0.15s, transform 0.15s; }
  .img-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.15); transform: translateY(-1px); }
  .img-thumb { width: 100%; aspect-ratio: 1; overflow: hidden; background: var(--code-bg); display: flex; align-items: center; justify-content: center; }
  .img-thumb img { width: 100%; height: 100%; object-fit: cover; }
  .img-info { padding: 6px 8px; }
  .img-name { font-size: 11px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .img-dir { font-size: 10px; color: var(--blue); margin-top: 1px; }
  .img-meta { font-size: 10px; color: var(--muted); margin-top: 1px; }
  .img-modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.85); z-index: 10000; display: flex; align-items: center; justify-content: center; }
  .img-modal-content { max-width: 95vw; max-height: 95vh; display: flex; flex-direction: column; align-items: center; }
  .img-modal-header { display: flex; justify-content: space-between; align-items: center; width: 100%; padding: 8px 12px; color: #fff; }
  .img-modal-name { font-size: 13px; }
  .img-modal-close { background: none; border: none; color: #fff; font-size: 24px; cursor: pointer; padding: 0 8px; }
  .img-paths-section { margin-bottom: 16px; }
  .img-path-row { display: flex; align-items: center; gap: 8px; padding: 4px 8px; border: 1px solid var(--border); border-radius: 3px; margin-bottom: 4px; background: var(--card-bg); }
  .img-path-val { flex: 1; font-size: 13px; cursor: pointer; }
  .img-path-val:hover { color: var(--blue); }
  .img-path-del { background: none; border: none; color: var(--red); font-size: 16px; cursor: pointer; padding: 0 4px; font-weight: bold; }
  .img-path-add { display: flex; gap: 8px; margin-top: 6px; }
  .img-path-add input { font-family: inherit; font-size: 13px; border: 1px solid var(--border); padding: 4px 8px; border-radius: 3px; background: var(--card-bg); color: var(--fg); flex: 1; }
  .img-path-add button { font-family: inherit; font-size: 12px; padding: 4px 12px; border: none; background: var(--blue); color: #fff; cursor: pointer; border-radius: 3px; }
  .study-chip { background: rgba(44,90,160,0.1); color: var(--blue); }
  .filter-dropdown-wrap { display: inline-block; position: relative; }
  .filter-search-input {
    font-family: inherit; font-size: 13px; border: 1px solid var(--border);
    padding: 6px 12px; border-radius: 4px; background: var(--card-bg); color: var(--fg);
    width: 170px; transition: border-color 0.15s;
  }
  .filter-search-input:focus { outline: none; border-color: var(--blue); }
  .filter-dropdown-list {
    position: absolute; top: 100%; left: 0; z-index: 50;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px;
    max-height: 240px; overflow-y: auto; min-width: 220px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }
  .filter-dropdown-item {
    padding: 6px 12px; cursor: pointer; font-size: 13px; display: flex; justify-content: space-between; align-items: center;
  }
  .filter-dropdown-item:hover, .filter-dropdown-item.active { background: var(--code-bg); color: var(--blue); }
  .manage-section { margin-bottom: 12px; }
  .manage-section h4 { font-size: 13px; margin-bottom: 6px; }
  .tm-name-edit { cursor: pointer; }
  .tm-name-edit:hover { color: var(--blue); }
"""


def get_all_css() -> str:
    """Concatenate all CSS sections."""
    return (CSS_RESET + CSS_LAYOUT + CSS_CARDS + CSS_TABLE +
            CSS_DETAIL + CSS_CODE + CSS_TIMELINE + CSS_COMPARE +
            CSS_COMPONENTS + CSS_STUDIES + CSS_IMAGES)
