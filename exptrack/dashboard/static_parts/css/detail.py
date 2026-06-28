"""CSS for experiment detail panel, info grid, and params/metrics tables."""

CSS_DETAIL = """
  .detail-summary { display: flex; gap: 12px; flex-wrap: wrap; padding: 10px 14px; background: var(--card-bg); border: 1px solid var(--border); border-radius: 4px; margin-bottom: 12px; align-items: center; }
  .detail-summary .sum-item { font-size: 13px; color: var(--muted); }
  .detail-summary .sum-item strong { color: var(--fg); }
  .detail-summary .sum-sep { color: var(--border); }
  .detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .detail-grid-full { grid-column: 1 / -1; }
  @media (max-width: 900px) { #exp-sidebar { display: none; } }
  /* Stack detail sections when the main canvas (not the viewport) is narrow —
     so a pinned Todos/Commands panel that squeezes the canvas also collapses
     the two-up grid into a single column. */
  @container main (max-width: 980px) {
    .detail-grid { grid-template-columns: 1fr; }
    .detail-export-bar { flex-direction: column; align-items: stretch; }
  }
  @container main (max-width: 600px) {
    .info-grid { grid-template-columns: 1fr; gap: 2px 0; }
    .info-grid .label { margin-top: 6px; }
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
  .info-grid { display: grid; grid-template-columns: 160px minmax(0, 1fr); gap: 8px 20px; margin-bottom: 20px; font-size: 14px; }
  .info-grid .label { color: var(--muted); font-weight: 500; }
  .info-grid > *:not(.label) { min-width: 0; word-break: break-word; overflow-wrap: anywhere; }
  .params-table, .metrics-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
  .params-table td, .metrics-table td { padding: 8px 14px; border-bottom: 1px solid var(--border); font-size: 14px; word-break: break-word; overflow-wrap: anywhere; }
  .params-table th, .metrics-table th { padding: 9px 14px; font-size: 13px; text-align: left; border-bottom: 2px solid var(--border); }
  .summary-card { background: var(--code-bg); border: 1px solid var(--border); padding: 16px; border-radius: 4px; margin-bottom: 20px; }
  .summary-card .summary-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; }
  .summary-card .summary-item { text-align: center; }
  .summary-card .summary-item .val { font-size: 18px; font-weight: 600; }
  .summary-card .summary-item .lbl { font-size: 12px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .session-origin-banner { display: flex; align-items: center; gap: 8px; margin: 0 0 14px 0; padding: 8px 12px; font-size: 13px; cursor: pointer; border-radius: var(--radius-sm, 4px); border: 1px solid var(--compare-accent, var(--purple)); background: var(--compare-bg, rgba(124,77,255,0.08)); color: var(--text-1, var(--fg)); }
  .session-origin-banner:hover { filter: brightness(0.97); }
  .session-origin-banner .so-icon { font-size: 14px; opacity: 0.85; }
  .session-origin-banner .so-text { flex: 1; min-width: 0; }
  .session-origin-banner .so-type { text-transform: capitalize; opacity: 0.9; }
  .session-origin-banner .so-go { font-size: 12px; color: var(--compare-accent, var(--purple)); white-space: nowrap; }

  /* Branch context: the sibling experiments tried from the same checkpoint. */
  .branch-context { margin: -6px 0 14px 0; padding: 8px 12px; border: 1px solid var(--border); border-radius: var(--radius-sm, 4px); background: var(--surface-2, var(--card-bg)); }
  .branch-context .bc-title { font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted); margin-bottom: 6px; }
  .branch-context .bc-sib { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px; padding: 3px 0; font-size: 12.5px; border-top: 1px solid var(--border); }
  .branch-context .bc-sib:first-of-type { border-top: none; }
  .branch-context .bc-sib.this { background: var(--accent-soft, var(--code-bg)); margin: 0 -8px; padding: 3px 8px; border-radius: 3px; border-top: none; }
  .branch-context .bc-sib-name { color: var(--blue); text-decoration: none; cursor: pointer; font-weight: 600; }
  .branch-context .bc-sib-name:hover { text-decoration: underline; }
  .branch-context .bc-sib-tag { font-size: 10.5px; border-radius: 8px; padding: 0 6px; white-space: nowrap; }
  .branch-context .bc-sib-tag.this { color: var(--accent); border: 1px solid var(--accent); }
  .branch-context .bc-sib-tag.ab { color: var(--branch-ab); border: 1px solid rgba(217,119,6,0.5); }
  .branch-context .bc-sib-res { font-family: 'IBM Plex Mono', monospace; font-size: 11.5px; color: var(--muted); flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .branch-context .bc-sib-exp { font-size: 11px; color: var(--blue); text-decoration: none; border: 1px solid var(--blue); padding: 0 6px; border-radius: 8px; cursor: pointer; white-space: nowrap; }

  /* Failure traceback panel: shown on failed runs with the captured traceback. */
  .error-panel { margin: -6px 0 14px 0; border: 1px solid var(--status-danger, var(--red)); border-radius: var(--radius-sm, 4px); background: var(--status-danger-soft, rgba(220,38,38,0.06)); overflow: hidden; }
  .error-panel-head { display: flex; align-items: center; gap: 8px; padding: 6px 12px; font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--status-danger, var(--red)); border-bottom: 1px solid var(--status-danger, var(--red)); }
  .error-panel-icon { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; border-radius: 50%; background: var(--status-danger, var(--red)); color: #fff; font-size: 11px; line-height: 1; }
  .error-panel-head .copy-btn { margin-left: auto; }
  .error-panel-tb { margin: 0; padding: 10px 12px; font-family: var(--font-mono, 'IBM Plex Mono', monospace); font-size: 12px; line-height: 1.45; color: var(--text-1, var(--fg)); white-space: pre; overflow: auto; max-height: 360px; }
"""
