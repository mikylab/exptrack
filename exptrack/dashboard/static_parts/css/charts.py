"""CSS for metric charts: toolbar, scale controls, chart containers, and overview preview."""

CSS_CHARTS = """
  .charts-tab-content { padding: 4px 0; }
  .chart-toolbar {
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
    padding: 10px 14px; margin-bottom: 14px;
    background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px;
  }
  .chart-toolbar label {
    font-size: 13px; color: var(--muted); font-weight: 500;
  }
  .chart-toolbar select {
    font-family: inherit; font-size: 13px; padding: 6px 12px;
    background: var(--code-bg); border: 1px solid var(--border);
    border-radius: 4px; color: var(--fg); cursor: pointer;
  }
  .chart-toolbar select:hover { border-color: var(--fg); }
  .chart-scale-group {
    display: flex; gap: 8px; align-items: center;
    margin-left: auto; flex-wrap: wrap;
  }
  .chart-scale-group label {
    font-size: 12px; color: var(--muted); font-weight: 400;
  }
  .chart-scale-group input {
    font-family: inherit; font-size: 13px; width: 80px;
    padding: 5px 10px; background: var(--code-bg);
    border: 1px solid var(--border); border-radius: 4px; color: var(--fg);
  }
  .chart-scale-group input:focus {
    border-color: var(--blue); outline: none;
  }
  .chart-scale-group .action-btn { font-size: 13px; padding: 6px 14px; }
  .chart-container { max-width: 700px; margin: 16px 0; }
  .chart-empty {
    padding: 40px 20px; text-align: center;
    color: var(--muted); font-size: 14px;
  }
  .charts-all-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
    gap: 16px; margin-top: 14px;
  }
  .charts-all-grid .chart-container { max-width: 100%; margin: 0; }
  .chart-view-toggle {
    display: inline-flex; border: 1px solid var(--border); border-radius: 4px; overflow: hidden;
  }
  .chart-view-toggle button {
    font-family: inherit; font-size: 13px; padding: 6px 16px;
    background: var(--code-bg); border: none; cursor: pointer;
    color: var(--muted); border-right: 1px solid var(--border);
  }
  .chart-view-toggle button:last-child { border-right: none; }
  .chart-view-toggle button:hover { background: var(--border); color: var(--fg); }
  .chart-view-toggle button.active { background: var(--fg); color: var(--bg); }
  .chart-preview-container { max-width: 100%; margin: 8px 0; }
  .chart-preview-link {
    display: inline-block; font-size: 12px; color: var(--blue);
    cursor: pointer; margin-top: 4px;
  }
  .chart-preview-link:hover { text-decoration: underline; }
  .artifact-path-cell {
    font-size: 12px; color: var(--muted);
    max-width: 250px; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
  }
  .artifact-path-cell:hover { white-space: normal; word-break: break-all; }
"""
