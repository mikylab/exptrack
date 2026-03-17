"""CSS for timeline events, badges, within-compare, and source viewer."""

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
  .tl-compare-bar { background: var(--code-bg); padding: 12px 16px; margin-bottom: 12px; border-radius: 6px; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 13px; border: 1px solid var(--border); }
  .tl-compare-bar button { font-family: inherit; font-size: 13px; background: var(--blue); color: #fff; border: none; padding: 6px 14px; cursor: pointer; border-radius: 4px; }
  .tl-compare-bar button:disabled { opacity: 0.4; cursor: not-allowed; }
  .tl-compare-bar button.cw-clear { background: var(--muted); }
  .cw-header h3 { font-size: 16px; margin-bottom: 4px; }
  .cw-subtitle { font-size: 13px; color: var(--muted); margin-bottom: 12px; }
  .cw-point { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border-radius: 4px; background: var(--card-bg); border: 1px dashed var(--border); min-width: 140px; }
  .cw-point.active { border-style: solid; }
  .cw-point-a.active { border-color: var(--blue); background: rgba(44,90,160,0.08); }
  .cw-point-b.active { border-color: #7c3aed; background: rgba(124,58,237,0.08); }
  .cw-point-label { font-weight: 700; font-size: 12px; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; flex-shrink: 0; }
  .cw-point-a .cw-point-label { background: var(--blue); }
  .cw-point-b .cw-point-label { background: #7c3aed; }
  .cw-point-desc { font-size: 12px; color: var(--fg); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cw-arrow { color: var(--muted); font-size: 18px; }
  .cw-actions { display: flex; gap: 6px; margin-left: auto; }
  .cw-badge { display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; font-size: 10px; font-weight: 700; color: #fff; }
  .cw-badge-a { background: var(--blue); }
  .cw-badge-b { background: #7c3aed; }
  .cw-marker-a { border-left: 3px solid var(--blue) !important; }
  .cw-marker-b { border-left: 3px solid #7c3aed !important; }
  .tl-seq-select { cursor: pointer; }
  .tl-seq-select:hover { background: rgba(44,90,160,0.08); }
  .tl-seq-select.selected { background: rgba(44,90,160,0.12); outline: 2px solid var(--blue); }
  .within-compare { background: var(--card-bg); border: 1px solid var(--border); padding: 20px; border-radius: 6px; margin-top: 16px; }
  .within-compare h3 { font-size: 14px; margin-bottom: 12px; }
  .cw-result-header { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  .cw-result-point { display: flex; align-items: center; gap: 6px; font-size: 13px; }
  .cw-section-title { font-size: 13px; font-weight: 600; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
  .cw-change-count { font-size: 11px; font-weight: 400; color: var(--muted); }
  .cw-filters { margin-bottom: 12px; font-size: 12px; color: var(--muted); }
  .cw-filters label { cursor: pointer; display: flex; align-items: center; gap: 4px; }
  .cw-table { font-size: 12px; }
  .cw-delta { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 3px; }
  .cw-delta-up { color: #059669; background: rgba(5,150,105,0.1); }
  .cw-delta-down { color: #dc2626; background: rgba(220,38,38,0.1); }
  .cw-delta-changed { color: #d97706; background: rgba(217,119,6,0.1); }
  .result-type-chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 4px; background: var(--code-bg); border: 1px solid var(--border); font-size: 12px; }
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
