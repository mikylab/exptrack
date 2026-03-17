"""CSS for experiment table, toolbar, actions, and filters."""

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
  td { padding: 10px 16px; border-bottom: 1px solid var(--border); border-right: 1px solid var(--border); font-size: 14px; }
  td:last-child { border-right: none; }
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
