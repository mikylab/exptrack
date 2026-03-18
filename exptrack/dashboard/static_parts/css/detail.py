"""CSS for experiment detail panel, info grid, and params/metrics tables."""

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
  .chart-selector { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .chart-selector select { font-family: inherit; font-size: 13px; padding: 4px 8px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 4px; color: var(--fg); }
  .chart-selector label { font-size: 12px; color: var(--muted); }
  .chart-scale-controls { display: flex; gap: 8px; align-items: center; margin-bottom: 4px; flex-wrap: wrap; }
  .chart-scale-controls label { font-size: 11px; color: var(--muted); }
  .chart-scale-controls input { font-family: inherit; font-size: 12px; width: 70px; padding: 2px 6px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 3px; color: var(--fg); }
  .chart-scale-controls button { font-family: inherit; font-size: 11px; padding: 2px 8px; background: var(--code-bg); border: 1px solid var(--border); border-radius: 3px; cursor: pointer; color: var(--fg); }
  .chart-scale-controls button:hover { background: var(--border); }
  .artifact-path-cell { font-size: 12px; color: var(--muted); max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .artifact-path-cell:hover { white-space: normal; word-break: break-all; }
  .summary-card { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; border-radius: 4px; margin-bottom: 20px; }
  .summary-card .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .summary-card .summary-item { text-align: center; }
  .summary-card .summary-item .val { font-size: 18px; font-weight: 600; }
  .summary-card .summary-item .lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
"""
